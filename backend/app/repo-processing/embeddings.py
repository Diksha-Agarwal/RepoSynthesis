from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
import os
from dotenv import load_dotenv

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")

class EmbeddingStoreFAISS:
    def __init__(self):
        # Initialize OpenAI embeddings
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large", api_key=openai_api_key)
        self.store = None

    def add_sections(self, sections):
        """
        Add a list of code sections (LangChain Documents or CodeSectionModels) to the FAISS vector store.
        """
        texts = [sec.page_content for sec in sections]
        # Handle both LangChain Document (has .metadata dict) and CodeSectionModel (has .file attr)
        metadatas = []
        for sec in sections:
            if hasattr(sec, 'metadata') and isinstance(sec.metadata, dict):
                metadatas.append({
                    "source": sec.metadata.get("source", "unknown"),
                    "language": sec.metadata.get("language", "unknown")
                })
            else:
                metadatas.append({
                    "source": getattr(sec, 'file', 'unknown'),
                    "language": "unknown"
                })

        if self.store is None:
            # Create a new FAISS store with metadata
            self.store = FAISS.from_texts(texts=texts, embedding=self.embeddings, metadatas=metadatas)
        else:
            # Add more sections to existing store with metadata
            self.store.add_texts(texts=texts, metadatas=metadatas)

    def save(self, path="faiss_index"):
        """
        Persist the FAISS index locally
        """
        if self.store:
            print("SAVING FAISS AT:", path)
            self.store.save_local(path)

    def load(self, path="faiss_index"):
        """
        Load an existing FAISS index
        """
        self.store = FAISS.load_local(path, self.embeddings, allow_dangerous_deserialization=True)
        return self.store


def load_vector_store(path: str):
    """Load a saved FAISS vector store from disk."""
    store = EmbeddingStoreFAISS()
    return store.load(path)