import os
import uuid
import base64
from typing import List, Dict, Any, Optional

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# MongoDB-backed docstore (optional)
from mongo_byte_store import MongoByteStore
from pymongo.errors import PyMongoError

# --- CRITICAL FIX: Ensure API Key is found ---
# 1. Get key from either name
google_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

# 2. If found, ensure it's set as GOOGLE_API_KEY for the library to see
if google_key:
    os.environ["GOOGLE_API_KEY"] = google_key
else:
    print("ERROR: GOOGLE_API_KEY or GEMINI_API_KEY not found in .env file.")
# ---------------------------------------------

# LangChain Imports
from langchain_chroma import Chroma
from langchain_core.stores import InMemoryByteStore
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.messages import HumanMessage

# Unstructured Import
from unstructured.partition.pdf import partition_pdf

class MultiModalRAG:
    def __init__(self):
        print("Initializing RAG Engine...")
        
        # 1. Setup Embeddings
        self.embedding_function = OpenAIEmbeddings()
        
        # 2. Setup Vector Store
        self.vectorstore = Chroma(
            collection_name="multi_modal_rag",
            embedding_function=self.embedding_function,
            persist_directory="./chroma_db"
        )
        
        # 3. Setup Doc Store
        mongo_uri = os.getenv("MONGODB_URI")
        mongo_db = os.getenv("MONGODB_DB", "multimodal")
        mongo_collection = os.getenv("MONGODB_DOCSTORE_COLLECTION", "rag_docstore")
        if mongo_uri:
            try:
                store = MongoByteStore(
                    mongo_uri=mongo_uri, db_name=mongo_db, collection_name=mongo_collection
                )
                # Fail fast if Mongo is unreachable (common when localhost isn't running).
                store._client.admin.command("ping")
                print("Using MongoDB for docstore persistence.")
                self.store = store
            except PyMongoError as e:
                print(f"MongoDB unavailable, falling back to in-memory docstore: {e}")
                self.store = InMemoryByteStore()
        else:
            print("Using in-memory docstore (no MONGODB_URI set).")
            self.store = InMemoryByteStore()
        self.id_key = "doc_id"
        
        # 4. Setup Retriever
        self.retriever = MultiVectorRetriever(
            vectorstore=self.vectorstore,
            byte_store=self.store,
            id_key=self.id_key,
        )

        # 5. Setup LLM (Passing key explicitly to avoid errors)
        self.model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.5,
            google_api_key=google_key  # <--- Explicitly passing the key here
        )

    def process_pdf(self, file_path: str):
        print(f"Processing: {file_path}")
        
        chunks = partition_pdf(
            filename=file_path,
            infer_table_structure=True,
            strategy="hi_res",
            extract_image_block_types=["Image"],
            extract_image_block_to_payload=True,
            chunking_strategy="by_title",
            max_characters=10000,
            combine_text_under_n_chars=2000,
            new_after_n_chars=6000,
        )

        tables = []
        texts = []
        images = []

        for chunk in chunks:
            if "CompositeElement" in str(type(chunk)):
                texts.append(chunk)
                if hasattr(chunk.metadata, "orig_elements"):
                    for el in chunk.metadata.orig_elements:
                        if "Table" in str(type(el)):
                            tables.append(el)
                        if "Image" in str(type(el)):
                            if hasattr(el.metadata, "image_base64") and el.metadata.image_base64:
                                images.append(el.metadata.image_base64)

        print(f"Found: {len(texts)} texts, {len(tables)} tables, {len(images)} images.")

        prompt_text = "Summarize the following content concisely for retrieval: {element}"
        prompt = ChatPromptTemplate.from_template(prompt_text)
        summarize_chain = {"element": lambda x: x} | prompt | self.model | StrOutputParser()

        # Batch summarize with checks
        text_summaries = summarize_chain.batch(texts, {"max_concurrency": 3}) if texts else []
        
        table_summaries = []
        if tables:
            tables_html = [t.metadata.text_as_html for t in tables]
            table_summaries = summarize_chain.batch(tables_html, {"max_concurrency": 3})

        image_summaries = ["Image content"] * len(images) if images else []

        self._index_batch(texts, text_summaries, "text")
        self._index_batch(tables, table_summaries, "table")
        self._index_batch(images, image_summaries, "image")
        
        return {"status": "success", "counts": {"texts": len(text_summaries), "tables": len(table_summaries), "images": len(image_summaries)}}

    def _index_batch(self, originals, summaries, type_label):
        if not originals or not summaries:
            return
        
        ids = [str(uuid.uuid4()) for _ in originals]
        summary_docs = [
            Document(page_content=s, metadata={self.id_key: ids[i], "type": type_label})
            for i, s in enumerate(summaries)
        ]
        self.vectorstore.add_documents(summary_docs)

        # Store the "parent" docs in the docstore as LangChain Documents.
        # MultiVectorRetriever expects `docstore` values to be Document instances.
        parent_docs: List[Document] = []
        for i, original in enumerate(originals):
            if type_label == "image":
                # `original` is base64 string when extracting images.
                page_content = str(original)
            else:
                # Unstructured elements (and table html) -> store as plain text.
                page_content = str(original)
            parent_docs.append(
                Document(page_content=page_content, metadata={"type": type_label})
            )

        self.retriever.docstore.mset(list(zip(ids, parent_docs)))

    def query(self, user_question: str):
        def parse_docs(docs):
            images: List[str] = []
            texts: List[str] = []

            for doc in docs:
                if isinstance(doc, Document):
                    doc_type = (doc.metadata or {}).get("type")
                    content = doc.page_content
                else:
                    doc_type = None
                    content = str(doc)

                # Prefer explicit typing from metadata to avoid misclassifying text as base64.
                if doc_type == "image":
                    images.append(str(content))
                    continue

                if doc_type in ("text", "table"):
                    texts.append(str(content))
                    continue

                # Fallback heuristic only if metadata is missing.
                try:
                    # validate=True ensures this is *actually* base64.
                    base64.b64decode(str(content), validate=True)
                    images.append(str(content))
                except Exception:
                    texts.append(str(content))

            return {"images": images, "texts": texts}

        def build_prompt(kwargs):
            docs_by_type = kwargs["context"]
            question = kwargs["question"]
            context_text = "\n\n".join(docs_by_type["texts"])
            
            content = [{"type": "text", "text": f"Context:\n{context_text}\n\nQuestion: {question}"}]
            for img in docs_by_type["images"]:
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})
            # ChatGoogleGenerativeAI expects a list of messages, not a single BaseMessage.
            return [HumanMessage(content=content)]

        chain = (
            {
                "context": self.retriever | RunnableLambda(parse_docs),
                "question": RunnablePassthrough(),
            }
            | RunnableLambda(build_prompt)
            | self.model
            | StrOutputParser()
        )

        response = chain.invoke(user_question)
        raw_docs = self.retriever.invoke(user_question)
        parsed = parse_docs(raw_docs)
        
        return {"answer": response, "images": parsed["images"]}