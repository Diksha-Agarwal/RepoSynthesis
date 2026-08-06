from langchain_text_splitters import (RecursiveCharacterTextSplitter,
                                     Language,)
# from models import CodeSectionModel, Document
from langchain_core.documents import Document
from pathlib import Path


# Map file extensions to Language enum
EXTENSION_TO_LANGUAGE = {
    ".py": Language.PYTHON,
    ".md": Language.MARKDOWN,
    ".tex": Language.LATEX,
    ".html": Language.HTML,
    ".htm": Language.HTML,
    ".sol": Language.SOL,
    ".cpp": Language.CPP,
    ".c": Language.CPP,
    ".java": Language.JAVA,
    ".rb": Language.RUBY,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".kt": Language.KOTLIN,
    ".swift": Language.SWIFT,
}



class CodeExtractor:

    def detect_language_from_document(doc: Document) -> Language | None:
        """Extract language from document's source metadata."""
        source = doc.metadata.get("source", "")
        extension = Path(source).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(extension)
    
    def split_documents_by_language(
        documents: list[Document],
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> list[Document]:
        """
        Split documents based on their programming language detected from source.
        Groups documents by language and applies language-specific splitting.
        """
        # Group documents by detected language
        docs_by_language = {}
        
        for doc in documents:
            language = CodeExtractor.detect_language_from_document(doc)
            if language is None:
                language_key = "unknown"
            else:
                language_key = language.value
            
            if language_key not in docs_by_language:
                docs_by_language[language_key] = []
            docs_by_language[language_key].append(doc)
        
        # Split each language group with appropriate splitter
        all_splits = []
        
        for language_key, docs in docs_by_language.items():
            print(f"Processing {len(docs)} documents with language: {language_key}")
            
            # Convert back to Language enum if not 'unknown'
            if language_key == "unknown":
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            else:
                language = Language(language_key)
                splitter = RecursiveCharacterTextSplitter.from_language(
                    language=language,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            
            # Split the documents in this language group
            splits = splitter.split_documents(docs)
            all_splits.extend(splits)
            print(f"  → Created {len(splits)} chunks")
        
        return all_splits


    # @staticmethod
    # def extract_code_sections(docs: list[Document]) -> list[CodeSectionModel]:
    #     """
    #     Split documents into code chunks and attach metadata
    #     """
    #     splitter = RecursiveCharacterTextSplitter(
    #         chunk_size=1000, # adjust as needed
    #         chunk_overlap=50,
    #         length_function=len,
    #         separators=["\n\n", "\n", " "],
    #         language=None
    #     )
    #     sections = []
    #     for doc in docs:
    #         chunks = splitter.split_text(doc.page_content)
    #         for idx, chunk in enumerate(chunks):
    #             sections.append(CodeSectionModel(
    #                 content=chunk,
    #                 file=doc.metadata.get("source", "unknown"),
    #                 type="code_chunk",
    #                 start_line=0,
    #                 end_line=0
    #             ))
    #     return sections