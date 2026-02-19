import os
import uuid
import base64
from typing import List, Dict, Any, Optional

# Load environment variables
from dotenv import load_dotenv
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_DOTENV = _HERE / ".env"
if not _DOTENV.exists():
    _DOTENV = _ROOT / ".env"
load_dotenv(dotenv_path=_DOTENV)


try:
    from .mongo_byte_store import MongoByteStore
except ImportError:
    from mongo_byte_store import MongoByteStore
from pymongo.errors import PyMongoError


google_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if google_key:
    os.environ["GOOGLE_API_KEY"] = google_key
else:
    print("ERROR: GOOGLE_API_KEY or GEMINI_API_KEY not found in .env file.")

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


from unstructured.partition.pdf import partition_pdf

class MultiModalRAG:
    def __init__(self):
        print("Initializing RAG Engine...")
        
        self.embedding_function = OpenAIEmbeddings()
        
        self.vectorstore = Chroma(
            collection_name="multi_modal_rag",
            embedding_function=self.embedding_function,
            persist_directory="./chroma_db"
        )

        mongo_uri = os.getenv("MONGODB_URI")
        mongo_db = os.getenv("MONGODB_DB", "multimodal")
        mongo_collection = os.getenv("MONGODB_DOCSTORE_COLLECTION", "rag_docstore")
        if mongo_uri:
            try:
                store = MongoByteStore(
                    mongo_uri=mongo_uri, db_name=mongo_db, collection_name=mongo_collection
                )
            
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
        
        self.retriever = MultiVectorRetriever(
            vectorstore=self.vectorstore,
            byte_store=self.store,
            id_key=self.id_key,
        )

        self.model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.5,
            google_api_key=google_key  
        )

    def process_pdf(self, file_path: str, *, user_id: str, session_id: Optional[str] = None):
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

     
        for el in chunks:
            t = str(type(el))
            if "Table" in t:
                tables.append(el)
                continue
            if "Image" in t:
                b64 = getattr(getattr(el, "metadata", None), "image_base64", None)
                if b64:
                    images.append(b64)
                continue
            texts.append(el)

        print(f"Found: {len(texts)} texts, {len(tables)} tables, {len(images)} images.")

        prompt_text = "Summarize the following content concisely for retrieval: {element}"
        prompt = ChatPromptTemplate.from_template(prompt_text)
        summarize_chain = {"element": lambda x: x} | prompt | self.model | StrOutputParser()

        text_summaries = summarize_chain.batch(texts, {"max_concurrency": 3}) if texts else []
        
        table_summaries = []
        if tables:
            tables_html = [t.metadata.text_as_html for t in tables]
            table_summaries = summarize_chain.batch(tables_html, {"max_concurrency": 3})

        image_summaries = ["Image content"] * len(images) if images else []

        base_meta = {"user_id": user_id, "session_id": session_id}
        self._index_batch(texts, text_summaries, "text", base_meta=base_meta)
        self._index_batch(tables, table_summaries, "table", base_meta=base_meta)
        self._index_batch(images, image_summaries, "image", base_meta=base_meta)
        
        return {"status": "success", "counts": {"texts": len(text_summaries), "tables": len(table_summaries), "images": len(image_summaries)}}

    def _index_batch(self, originals, summaries, type_label, *, base_meta: Optional[dict] = None):
        if not originals or not summaries:
            return
        
        ids = [str(uuid.uuid4()) for _ in originals]
        summary_docs = [
            Document(
                page_content=s,
                metadata={
                    self.id_key: ids[i],
                    "type": type_label,
                    **(base_meta or {}),
                },
            )
            for i, s in enumerate(summaries)
        ]
        self.vectorstore.add_documents(summary_docs)

      
        parent_docs: List[Document] = []
        for i, original in enumerate(originals):
            if type_label == "image":
        
                page_content = str(original)
            else:
              
                page_content = str(original)
            parent_docs.append(
               
                Document(
                    page_content=page_content,
                    metadata={
                        "type": type_label,
                        self.id_key: ids[i],
                        **(base_meta or {}),
                    },
                )
            )

        self.retriever.docstore.mset(list(zip(ids, parent_docs)))

    def query(
        self,
        user_question: str,
        chat_history: Optional[List[dict]] = None,
        *,
        user_id: str,
        session_id: Optional[str] = None,
    ):
        def wants_visual_context(question: str) -> bool:
            q = (question or "").lower()
            keywords = [
                "image",
                "photo",
                "picture",
                "figure",
                "diagram",
                "chart",
                "graph",
                "screenshot",
                "logo",
                "table",
            ]
            return any(k in q for k in keywords)

        def wants_exhaustive_projects_list(question: str) -> bool:
            """Detect questions that expect complete enumeration (e.g., all projects)."""
            q = (question or "").lower()
            has_projects = "project" in q or "projects" in q
            has_list_intent = any(
                k in q
                for k in [
                    "list all",
                    "all projects",
                    "every project",
                    "show all",
                    "what are the projects",
                    "projects included",
                    "projects in",
                ]
            )
            return has_projects and has_list_intent

        def is_projects_question(question: str) -> bool:
            q = (question or "").lower()
            return "project" in q or "projects" in q

        def retrieve_parent_docs(question: str, *, types: List[str], k_per_type: int) -> List[Document]:
            """Retrieve parent docs by filtering summary docs by metadata type.

            This avoids the common failure mode where image-only results dominate
            the prompt and the model describes the photo instead of answering.
            """
            summary_docs: List[Document] = []
            for t in types:
            
                clauses: List[dict] = [{"type": t}, {"user_id": user_id}]
                if session_id is not None:
                    clauses.append({"session_id": session_id})
                filt: dict = clauses[0] if len(clauses) == 1 else {"$and": clauses}
                summary_docs.extend(
                    self.vectorstore.similarity_search(
                        question, k=k_per_type, filter=filt
                    )
                )

            ids: List[str] = []
            for d in summary_docs:
                doc_id = (d.metadata or {}).get(self.id_key)
                if doc_id and doc_id not in ids:
                    ids.append(doc_id)

            parents = self.retriever.docstore.mget(ids)
            return [d for d in parents if isinstance(d, Document)]

        def retrieve_all_parent_docs(*, types: List[str], limit: int = 200) -> List[Document]:
            """Retrieve all parent docs from the docstore (bounded)."""
            ids: List[str] = []
            try:
                for k in self.store.yield_keys():
                    ids.append(str(k))
                    if len(ids) >= limit:
                        break
            except Exception:
                return []

            parents = self.retriever.docstore.mget(ids)
            docs = [d for d in parents if isinstance(d, Document)]
            if not types:
                filtered = docs
            else:
                filtered = [d for d in docs if (d.metadata or {}).get("type") in types]

            # Session/user scope filter
            scoped: List[Document] = []
            for d in filtered:
                md = d.metadata or {}
                if md.get("user_id") != user_id:
                    continue
                if md.get("session_id") != session_id:
                    continue
                scoped.append(d)
            return scoped

        def clamp_text(text: str, max_chars: int = 25000) -> str:
            if len(text) <= max_chars:
                return text
            head = text[: int(max_chars * 0.65)]
            tail = text[-int(max_chars * 0.30) :]
            return head + "\n\n...[truncated]...\n\n" + tail

        def dedupe_docs(docs: List[Document]) -> List[Document]:
            seen: set[str] = set()
            out: List[Document] = []
            for d in docs:
                key = (d.metadata or {}).get(self.id_key) or d.page_content[:200]
                if key in seen:
                    continue
                seen.add(str(key))
                out.append(d)
            return out

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

                if doc_type == "image":
                    images.append(str(content))
                    continue

                if doc_type in ("text", "table"):
                    texts.append(str(content))
                    continue

                try:
                    base64.b64decode(str(content), validate=True)
                    images.append(str(content))
                except Exception:
                    texts.append(str(content))

            return {"images": images, "texts": texts}

        def build_history_text(history: Optional[List[dict]], max_turns: int = 6) -> str:
            if not history:
                return ""
        
            recent = history[-(max_turns * 2):]
            lines = []
            for msg in recent:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    lines.append(f"User: {content}")
                elif role == "assistant":
                    lines.append(f"Assistant: {content}")
            return "\n".join(lines)

        def build_prompt(kwargs):
            docs_by_type = kwargs["context"]
            question = kwargs["question"]
            context_text = clamp_text("\n\n".join(docs_by_type["texts"]))
            history_text = build_history_text(chat_history)

            system_parts = [
                "You are a helpful assistant answering questions using the provided context.",
                "Answer directly and concisely using only the context. If the context does not contain the answer, say so.",
                "If the user asks about projects, list all distinct projects you can find in the context.",
            ]
            if history_text:
                system_parts.append(
                    f"\n--- Previous conversation ---\n{history_text}\n--- End of previous conversation ---"
                )
            system_parts.append(f"\nContext:\n{context_text}\n\nQuestion: {question}")

            content = [{"type": "text", "text": "\n".join(system_parts)}]

            include_images = wants_visual_context(question) or (
                not docs_by_type["texts"] and bool(docs_by_type["images"])
            )
            if include_images:
                for img in docs_by_type["images"][:2]:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img}"},
                        }
                    )
          
            return [HumanMessage(content=content)]

        visual = wants_visual_context(user_question)
        exhaustive_projects = wants_exhaustive_projects_list(user_question)
        projects_q = is_projects_question(user_question)

        parent_docs: List[Document] = retrieve_parent_docs(
            user_question, types=["text", "table"], k_per_type=12
        )

        if projects_q:
            parent_docs.extend(
                retrieve_parent_docs("projects", types=["text", "table"], k_per_type=12)
            )
            parent_docs.extend(
                retrieve_parent_docs("key projects", types=["text", "table"], k_per_type=8)
            )
            parent_docs = dedupe_docs(parent_docs)

        if exhaustive_projects:
            all_docs = retrieve_all_parent_docs(types=["text", "table"], limit=200)
            if all_docs:
                parent_docs = all_docs

        if visual:
            parent_docs.extend(
                retrieve_parent_docs(user_question, types=["image"], k_per_type=2)
            )
            parent_docs = dedupe_docs(parent_docs)

        chain = (
            {
                "context": RunnableLambda(lambda q: parse_docs(parent_docs)),
                "question": RunnablePassthrough(),
            }
            | RunnableLambda(build_prompt)
            | self.model
            | StrOutputParser()
        )

        response = chain.invoke(user_question)
        parsed = parse_docs(parent_docs)
        
        return {"answer": response, "images": parsed["images"]}