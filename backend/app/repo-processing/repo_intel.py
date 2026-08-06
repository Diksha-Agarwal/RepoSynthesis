from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from models import RepoIntelModel
import json
import os
from dotenv import load_dotenv


load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")

class RepoIntel:
    _llm = None
    
    @classmethod
    def get_llm(cls):
        if cls._llm is None:
            cls._llm = ChatOpenAI(
                model="gpt-4o-mini", 
                temperature=0.4
            )
        return cls._llm
    
    @staticmethod
    def generate_report_from_documents(docs) -> RepoIntelModel:
        """
        Uses LangChain LLM to summarize repo info
        """
        prompt = ChatPromptTemplate.from_template(
            """You are an expert software engineer. 
            Analyze the following code files and provide:
            1. Stack / language
            2. Framework (if any)
            3. Entry points (main.py, app.py, index.js)
             Give me repository type and structure . Detect Important files automatically.
             Extract File metadata. Parse config files for stack understanding. Detect Dependencies and framework
             Skip patterns applied (node_modules, .git, etc.). 
             I want all this from a file when you decode it. Below is an example output;
             "System processes repository → Shows "Detected: Python FastAPI 
            project" → "Found 12 API endpoints" → "Identified main.py as entry 
            point" → "Prepared 150 code sections for analysis" → User searches 
            "authentication" and gets relevant code section"
            This is how I want you to analyze the file and give me result.

            List your answer as JSON with keys: stack, framework, entry_points.
            Code files:
            {docs}
            """
        )
        output_parser = StrOutputParser()
        # chain = LLMChain(llm=RepoIntel.llm, prompt=prompt)
        chain = prompt | RepoIntel.get_llm() | output_parser
        # print("CHAIN: ", chain)
        combined_text = "\n\n".join([doc.page_content for doc in docs[:10]]) # first 10 files to save tokens
        result = chain.invoke({"docs": combined_text})
        
        # Strip markdown code blocks and handle multiple JSON objects
        result = result.strip()
        if result.startswith("```json"):
            result = result[7:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()
        
        # Extract first JSON object if multiple exist
        try:
            # Find first complete JSON object
            brace_count = 0
            start_idx = result.find('{')
            if start_idx == -1:
                raise ValueError("No JSON object found")
            
            for i in range(start_idx, len(result)):
                if result[i] == '{':
                    brace_count += 1
                elif result[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        result = result[start_idx:i+1]
                        break
            
            return json.loads(result)
        except Exception as e:
            print(f"⚠️  RepoIntel JSON parse failed: {e}")
            print(f"Raw output: {result[:200]}...")
            return {"stack": "Unknown", "framework": "Unknown", "entry_points": []}