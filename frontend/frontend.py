import streamlit as st
import requests
import time

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="GraphFlow Analysis", layout="wide")
st.title("🔍 Repository Analysis with GraphFlow")

# Enable auto-rerun every 5 seconds if analysis is running
def check_auto_refresh():
    if st.session_state.get('active_project'):
        proj_id = st.session_state.active_project.get('id')
        if proj_id:
            preprocess = st.session_state.preprocessing_status.get(proj_id, "not_started")
            analysis = st.session_state.analysis_status.get(proj_id, "not_started")
            # Auto-refresh if something is running
            if preprocess == "running" or analysis == "running":
                time.sleep(5)
                st.rerun()

# Session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = None
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False

# Authentication
if not st.session_state.logged_in:
    tab1, tab2 = st.tabs(["Login", "Signup"])
    
    with tab1:
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            resp = requests.post(f"{BACKEND_URL}/login", json={"username": username, "password": password})
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.logged_in = True
                st.session_state.username = data.get('username', username)
                st.session_state.is_admin = data.get('is_admin', False)
                st.rerun()
            else:
                st.error("Invalid credentials")
    
    with tab2:
        username = st.text_input("Username", key="signup_user")
        password = st.text_input("Password", type="password", key="signup_pass")
        if st.button("Create Account"):
            resp = requests.post(f"{BACKEND_URL}/signup", json={"username": username, "password": password})
            if resp.status_code == 200:
                st.success("Account created! Please login")
            else:
                st.error("Username already exists")

else:
    # Initialize session state - simplified
    defaults = {
        'active_project': None,
        'messages': {},  # Per-project message display (UI only)
        'preprocessing_status': {},
        'analysis_status': {},
        'analysis_config': {},
        'show_results': {}
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    
    # Admin panel check
    if st.session_state.get('show_admin'):
        st.header("👑 Admin Dashboard")
        resp = requests.get(f"{BACKEND_URL}/admin/projects", params={"admin_username": st.session_state.username})
        if resp.status_code == 200:
            projects = resp.json()
            for p in projects:
                with st.expander(f"📁 {p['name']} (User: {p['username']})"):
                    if p['zip_filename']:
                        if st.button("⬇️ Download ZIP", key=f"zip_{p['id']}"):
                            zip_url = f"{BACKEND_URL}/admin/projects/{p['id']}/download?admin_username={st.session_state.username}"
                            st.markdown(f"[Download ZIP]({zip_url})")
                    else:
                        st.caption("No ZIP file available")
        if st.button("← Back"):
            st.session_state.show_admin = False
            st.rerun()
        st.stop()
    
    # SIDEBAR: Projects List (Chat-app style)
    with st.sidebar:
        st.success(f"👤 {st.session_state.username}")
        if st.session_state.is_admin:
            st.warning("👑 ADMIN")
            if st.button("👑 Admin Panel", use_container_width=True):
                st.session_state.show_admin = True
                st.rerun()
            st.divider()
        
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.is_admin = False
            st.session_state.active_project = None
            st.rerun()
        
        st.divider()
        st.subheader("📁 Projects")
        
        # Upload new project
        with st.expander("➕ New Project"):
            tab1, tab2 = st.tabs(["📦 ZIP File", "🌐 GitHub URL"])
            
            with tab1:
                uploaded_file = st.file_uploader("Upload ZIP", type=['zip'], label_visibility="collapsed")
                if uploaded_file and st.button("Upload ZIP", use_container_width=True):
                    files = {"file": uploaded_file}
                    data = {"username": st.session_state.username}
                    resp = requests.post(f"{BACKEND_URL}/projects/upload", files=files, data=data)
                    if resp.status_code == 200:
                        st.success("✅ Uploaded!")
                        st.rerun()
                    else:
                        st.error(f"❌ Failed: {resp.text}")
            
            with tab2:
                github_url = st.text_input(
                    "GitHub Repository URL",
                    placeholder="https://github.com/username/repo",
                    label_visibility="collapsed"
                )
                project_name = st.text_input(
                    "Project Name (optional)",
                    placeholder="My Awesome Project",
                    label_visibility="collapsed"
                )
                if st.button("Add GitHub Repo", use_container_width=True, disabled=not github_url):
                    if github_url:
                        data = {
                            "username": st.session_state.username,
                            "github_url": github_url,
                            "name": project_name if project_name else github_url.split('/')[-1]
                        }
                        resp = requests.post(f"{BACKEND_URL}/projects/upload", data=data)
                        if resp.status_code == 200:
                            st.success("✅ GitHub repo added!")
                            st.rerun()
                        else:
                            st.error(f"❌ Failed: {resp.text}")
        
        # List projects
        resp = requests.get(f"{BACKEND_URL}/projects", params={"username": st.session_state.username})
        if resp.status_code == 200:
            projects = resp.json()
            if projects:
                for proj in projects:
                    is_active = st.session_state.active_project and st.session_state.active_project['id'] == proj['id']
                    button_type = "primary" if is_active else "secondary"
                    # Add icon based on source
                    icon = "🌐" if proj.get('github_url') else "📦"
                    status_icon = '🟢' if is_active else '⚪'
                    button_label = f"{status_icon} {icon} {proj['name']}"
                    
                    if st.button(button_label, key=f"proj_{proj['id']}", use_container_width=True, type=button_type):
                        st.session_state.active_project = proj
                        # Initialize project state
                        for state_dict in ['messages', 'preprocessing_status', 'analysis_status', 'analysis_config', 'show_results']:
                            if proj['id'] not in st.session_state[state_dict]:
                                default_val = [] if state_dict == 'messages' else ("not_started" if 'status' in state_dict else (None if state_dict == 'analysis_config' else False))
                                st.session_state[state_dict][proj['id']] = default_val
                        st.rerun()
            else:
                st.info("No projects yet")
    
    # MAIN AREA: Chat Interface (Always visible)
    if not st.session_state.active_project:
        st.info("👈 Select a project from the sidebar to start chatting")
        st.stop()
    
    project = st.session_state.active_project
    project_id = project['id']
    
    # Check preprocessing status
    preprocess_status = st.session_state.preprocessing_status.get(project_id, "not_started")
    analysis_status = st.session_state.analysis_status.get(project_id, "not_started")
    
    # Sync preprocessing status with backend if session state says running
    if preprocess_status == "running":
        try:
            resp = requests.get(f"{BACKEND_URL}/projects/{project_id}/preprocess/status", timeout=2)
            if resp.status_code == 200:
                backend_status = resp.json()
                # Update session state to match backend
                if backend_status.get("status") != "running":
                    st.session_state.preprocessing_status[project_id] = backend_status.get("status", "not_started")
                    preprocess_status = backend_status.get("status", "not_started")
        except:
            # If backend check fails, keep current state
            pass
    
    # Sync analysis status with backend - check if running to detect completion
    if preprocess_status == "completed":
        try:
            resp = requests.get(f"{BACKEND_URL}/projects/{project_id}/status", timeout=2)
            if resp.status_code == 200:
                backend_status = resp.json()
                backend_analysis_status = backend_status.get("status", "not_started")
                # Always sync if backend says something different
                if backend_analysis_status != analysis_status:
                    analysis_status = backend_analysis_status
                    st.session_state.analysis_status[project_id] = analysis_status
        except:
            pass
    
    # Configuration UI (if needed)
    show_config = preprocess_status == "not_started" and not st.session_state.analysis_config.get(project_id)
    
    if show_config:
        st.header(f"⚙️ Configure Analysis for {project['name']}")
        
        # Show project source info
        if project.get('github_url'):
            st.info(f"🌐 **GitHub Repository:** {project['github_url']}")
        else:
            st.info(f"📦 **ZIP File:** {project.get('zip_filename', 'Uploaded file')}")
        
        with st.form(key=f"config_form_{project_id}"):
            st.subheader("Select Reports to Generate")
            col1, col2 = st.columns(2)
            with col1:
                sde_enabled = st.checkbox("📊 SDE Report (Software Engineering)", value=True)
            with col2:
                pm_enabled = st.checkbox("📋 PM Report (Product Management)", value=True)
            
            st.divider()
            
            st.subheader("Analysis Configuration")
            col3, col4 = st.columns(2)
            with col3:
                depth = st.selectbox(
                    "Analysis Depth",
                    ["quick", "standard", "deep"],
                    index=0,  # Default to "quick" for faster results
                    help="Quick: Fast & concise (⚡ Recommended) | Standard: Balanced | Deep: Comprehensive"
                )
            with col4:
                verbosity = st.selectbox(
                    "Report Verbosity",
                    ["low", "medium", "high"],
                    index=0,  # Default to "low" for faster processing
                    help="Low: Concise (⚡ Recommended) | Medium: Balanced | High: Detailed"
                )
            
            # Show recommendation for speed
            if depth == "quick" and verbosity == "low":
                st.success("⚡ **Fast Mode** - Analysis will complete quickly and chat will get insights sooner!")
            
            submitted = st.form_submit_button("🚀 Start Analysis", type="primary", use_container_width=True)
            
            if submitted:
                if not sde_enabled and not pm_enabled:
                    st.error("⚠️ Please select at least one report type")
                else:
                    personas_list = []
                    if sde_enabled:
                        personas_list.append("SDE")
                    if pm_enabled:
                        personas_list.append("PM")
                    personas = ",".join(personas_list)
                    
                    # Save configuration
                    st.session_state.analysis_config[project_id] = {
                        "personas": personas,
                        "depth": depth,
                        "verbosity": verbosity
                    }
                    
                    # Start preprocessing
                    st.session_state.preprocessing_status[project_id] = "running"
                    resp = requests.post(f"{BACKEND_URL}/projects/{project_id}/preprocess")
                    if resp.status_code != 200:
                        st.error(f"❌ Failed to start preprocessing: {resp.text}")
                        st.session_state.preprocessing_status[project_id] = "not_started"
                    st.rerun()
        
        st.divider()
    
    # Auto-start analysis if preprocessing just completed and analysis not started
    if preprocess_status == "completed" and analysis_status == "not_started":
        config = st.session_state.analysis_config.get(project_id)
        if config:  # Only auto-start if user configured it
            personas = config.get("personas", "SDE,PM")
            depth = config.get("depth", "quick")
            verbosity = config.get("verbosity", "low")
            
            try:
                resp = requests.post(
                    f"{BACKEND_URL}/projects/{project_id}/analyze/graphflow", 
                    data={"personas": personas, "depth": depth, "verbosity": verbosity},
                    timeout=5
                )
                if resp.status_code == 200:
                    st.session_state.analysis_status[project_id] = "running"
                    st.success("🚀 Analysis started automatically!")
                    st.rerun()
            except Exception as e:
                st.warning(f"Could not auto-start analysis: {e}")
    
    # Preprocessing monitor (if running)
    if preprocess_status == "running":
        col1, col2 = st.columns([3, 1])
        with col1:
            st.info(f"🔄 Preprocessing...")
        with col2:
            if st.button("🔄 Refresh", key="refresh_preprocess"):
                st.rerun()
        
        try:
            resp = requests.get(f"{BACKEND_URL}/projects/{project_id}/preprocess/status", timeout=2)
            if resp.status_code == 200:
                status = resp.json()
                
                # If backend says not_started but session says running, reset session
                if status['status'] == 'not_started':
                    st.session_state.preprocessing_status[project_id] = "not_started"
                    st.warning("⚠️ Preprocessing status lost. Please start preprocessing again.")
                    st.rerun()
                
                if status['status'] == 'running':
                    st.caption(f"📦 {status.get('current_step', 'Processing...')}")
                    st.info("⏱️ Click 'Refresh' button to update status")
                elif status['status'] == 'completed':
                    st.success("✅ Preprocessing complete!")
                    st.session_state.preprocessing_status[project_id] = "completed"
                    st.rerun()
                elif status['status'] == 'failed':
                    st.error(f"❌ Preprocessing failed: {status.get('error', 'Unknown error')}")
                    st.session_state.preprocessing_status[project_id] = "not_started"
                    if st.button("🔄 Retry"):
                        st.rerun()
        except requests.exceptions.RequestException as e:
            st.error(f"⚠️ Cannot connect to backend: {str(e)}")
            st.session_state.preprocessing_status[project_id] = "not_started"
            if st.button("🔄 Retry Connection"):
                st.rerun()
        except Exception as e:
            st.error(f"❌ Error checking status: {str(e)}")
            st.session_state.preprocessing_status[project_id] = "not_started"
        
        st.divider()    # CHAT INTERFACE - ALWAYS SHOW (even during config/preprocessing)
    st.header(f"💬 Chat - {project['name']}")
    
    # Show preprocessing/analysis status indicator
    if preprocess_status == "completed" and analysis_status == "not_started":
        st.info("ℹ️ You can chat now or run analysis for deeper insights")
    
    # CONTROL BUTTONS - Show after analysis completes
    if analysis_status == "completed":
        st.subheader("🎮 Analysis Controls")
        btn_col1, btn_col2 = st.columns(2)
        
        with btn_col1:
            if st.button("📊 VIEW RESULTS", use_container_width=True, type="primary"):
                st.session_state.show_results[project_id] = True
                st.rerun()
        
        with btn_col2:
            if preprocess_status == "completed":
                if st.button("🗑️ CLEAR CHAT", use_container_width=True):
                    requests.post(f"{BACKEND_URL}/projects/{project_id}/chat/clear")
                    st.session_state.messages[project_id] = []
                    st.rerun()
        
        st.divider()
    
    # Top bar with analysis status
    col_status, col_btns = st.columns([3, 1])
    with col_status:
        if analysis_status == "running":
            try:
                resp = requests.get(f"{BACKEND_URL}/projects/{project_id}/status", timeout=2)
                if resp.status_code == 200:
                    status = resp.json()
                    progress = status.get("progress", 0)
                    current_activity = status.get('current_activity', 'Running...')
                    
                    st.progress(progress / 100, text=f"🔄 **Analyzing...** {progress}%")
                    st.caption(f"_{current_activity}_")
            except:
                st.warning("⏳ Analysis running...")
        elif analysis_status == "completed":
            st.success("✅ **Analysis Complete!**")
        elif preprocess_status == "completed":
            st.info("💬 Chat is ready! Analysis optional.")
    
    with col_btns:
        # Status refresh button - manual refresh instead of auto-refresh
        if analysis_status == "running":
            if st.button("🔄 Refresh", key="refresh_status", use_container_width=True):
                st.rerun()
    
    # Show analysis results if requested
    if st.session_state.show_results.get(project_id, False):
            with st.expander("📊 Analysis Results", expanded=True):
                try:
                    import os
                    result_path = f"data/projects/{project_id}/analysis_result.json"
                    if os.path.exists(result_path):
                        import json
                        with open(result_path, 'r', encoding='utf-8') as f:
                            result = json.load(f)
                        
                        # Display each agent's output
                        if 'agents' in result:
                            for agent_name, agent_output in result['agents'].items():
                                with st.container():
                                    st.markdown(f"### {agent_name}")
                                    st.markdown(agent_output)
                                    st.divider()
                        else:
                            st.json(result)
                        
                        if st.button("✖ Close Results"):
                            st.session_state.show_results[project_id] = False
                            st.rerun()
                    else:
                        st.warning("Results file not found yet")
                except Exception as e:
                    st.error(f"Error loading results: {str(e)}")
    
    st.divider()
    
    # Chat controls header
    st.subheader("💬 Conversation")
    
    # Display message history (UI only)
    for msg in st.session_state.messages.get(project_id, []):
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("sources"):
                sources = [s for s in msg.get("sources", []) if s and s != 'unknown']
                if sources:
                    with st.expander("📎 Sources", expanded=False):
                        for src in sources:
                            clean_src = src.replace('\\', '/').split('/')[-1] if '/' in src or '\\' in src else src
                            st.caption(f"• {clean_src}")
            if msg.get("using_partial"):
                st.caption("⚡ _Using partial analysis (faster)_")
            elif msg.get("has_analysis"):
                st.caption("✨ _Enhanced with analysis insights_")
    
    # Chat input - enabled after preprocessing completes (analysis optional)
    chat_disabled = preprocess_status != "completed"
    chat_placeholder = "Preprocessing required..." if chat_disabled else f"Ask about {project['name']}..."
    
    if prompt := st.chat_input(chat_placeholder, disabled=chat_disabled):
        # Show user message immediately
        st.session_state.messages[project_id].append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.write(prompt)
        
        # Show assistant response with visible loading
        with st.chat_message("assistant"):
            # Create a placeholder that shows immediately
            thinking_placeholder = st.empty()
            thinking_placeholder.markdown("🤔 _Thinking..._")
            
            try:
                import time
                
                # Call backend
                response = requests.post(
                    f"{BACKEND_URL}/projects/{project_id}/ask",
                    data={"question": prompt},
                    timeout=60
                )
                
                # Clear the thinking indicator
                thinking_placeholder.empty()
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data["answer"]
                    sources = data.get("sources", [])
                    response_time = data.get("time", 0)
                    has_analysis = data.get("has_analysis", False)
                    using_partial = data.get("using_partial", False)
                    
                    # Display answer
                    st.write(answer)
                    
                    # Show metadata
                    col1, col2, col3 = st.columns([2, 2, 1])
                    with col1:
                        if sources and sources != ['unknown']:
                            with st.expander("📎 Sources", expanded=False):
                                for src in sources:
                                    # Clean up the source path
                                    if src and src != 'unknown':
                                        clean_src = src.replace('\\', '/').split('/')[-1] if '/' in src or '\\' in src else src
                                        st.caption(f"• {clean_src}")
                    with col2:
                        if using_partial:
                            st.caption("⚡ _Using partial analysis (faster)_")
                        elif has_analysis:
                            st.caption("✨ _Enhanced with analysis insights_")
                    with col3:
                        st.caption(f"⏱️ {response_time}s")
                    
                    # Save to message history
                    st.session_state.messages[project_id].append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                        "has_analysis": has_analysis,
                        "using_partial": using_partial
                    })
                else:
                    error_msg = f"Error: {response.text}"
                    st.error(error_msg)
                    st.session_state.messages[project_id].append({
                        "role": "assistant",
                        "content": error_msg
                    })
            except Exception as e:
                thinking_placeholder.empty()
                error_msg = f"Failed: {str(e)}"
                st.error(error_msg)
                st.session_state.messages[project_id].append({
                    "role": "assistant",
                    "content": error_msg
                })
        
        st.rerun()

# Auto-refresh if analysis/preprocessing is running (non-blocking)
check_auto_refresh()