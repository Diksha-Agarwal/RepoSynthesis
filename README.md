# AI-Powered Repository Analysis

An intelligent code analysis platform that uses multi-agent AI systems to analyze repositories and provide insights through an interactive chat interface.

![Project UI](assests/ui-screenshot.png)

## Features

- 🤖 **Multi-Agent Analysis**: Leverages specialized AI agents (SDE, PM, QA) to analyze codebases
- 💬 **Interactive Chat**: Ask questions about your codebase with context-aware responses
- 📊 **Comprehensive Reports**: Generate detailed architecture, API, and database insights
- 🌐 **GitHub Integration**: Analyze repositories directly from GitHub URLs
- 📦 **ZIP Upload**: Upload local projects for analysis
- 🔍 **Semantic Search**: Vector-based code search for intelligent context retrieval

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, LangChain
- **Frontend**: Streamlit
- **AI**: OpenAI GPT-4, AutoGen multi-agent framework
- **Vector Store**: FAISS for embeddings
- **Database**: SQLite

## Prerequisites

- Python 3.8+
- OpenAI API key

## Installation

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd FINAL
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   # Copy the example file
   copy .env.example .env
   
   # Edit .env and add your OpenAI API key
   OPENAI_API_KEY=your_actual_api_key_here
   ```

## Usage

### Start the Backend Server

```bash
cd backend/app
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

### Start the Frontend

In a new terminal:

```bash
cd frontend
streamlit run frontend.py
```

The web interface will open at `http://localhost:8501`

## How to Use

1. **Sign Up/Login**: Create an account or login to the platform
2. **Upload Project**: 
   - Upload a ZIP file of your codebase, or
   - Provide a GitHub repository URL
3. **Configure Analysis**: Select analysis depth and report types (SDE/PM)
4. **Preprocessing**: The system will extract and index your code
5. **Analysis**: AI agents analyze the codebase (optional but recommended)
6. **Chat**: Ask questions about your project - get instant, context-aware answers

## Project Structure

```
FINAL/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI application
│       ├── auth.py              # Authentication
│       ├── projects.py          # Project management
│       ├── agents/              # AI agent implementations
│       ├── repo-processing/     # Code extraction & embeddings
│       └── teams/               # Multi-agent coordination
├── frontend/
│   └── frontend.py              # Streamlit UI
├── requirements.txt             # Python dependencies
└── .env.example                 # Environment variables template
```

## API Endpoints

- `POST /signup` - Create new user account
- `POST /login` - User authentication
- `POST /projects/upload` - Upload project (ZIP or GitHub)
- `POST /projects/{id}/preprocess` - Start code preprocessing
- `POST /projects/{id}/analyze/graphflow` - Start AI analysis
- `POST /projects/{id}/ask` - Chat with your codebase

## Configuration

Analysis can be configured with:
- **Depth**: `quick`, `standard`, `deep`
- **Verbosity**: `low`, `medium`, `high`
- **Reports**: SDE (Software Engineering), PM (Product Management)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with [AutoGen](https://github.com/microsoft/autogen)
- Powered by [OpenAI GPT-4](https://openai.com/)
- UI framework: [Streamlit](https://streamlit.io/)
