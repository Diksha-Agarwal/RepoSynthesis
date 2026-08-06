"""
Research-Style Analysis Runner
ChatGPT Research mode for codebase analysis
"""

from typing import Dict, Any, Optional, List
import json
import asyncio
from pathlib import Path
from datetime import datetime

from app.models.schemas import AnalysisResult
from app.models.run_state import AnalysisRun, RunStatus, AgentStep
from app.config.analysis_config import AnalysisConfig
from app.teams.graphflow_team import GraphFlowCoordinator
from app.agents.utils import search_code

# Store running tasks globally to prevent cancellation
_running_tasks: Dict[str, asyncio.Task] = {}

# Store pause flags globally so different ResearchRunner instances can communicate
_pause_flags: Dict[str, bool] = {}


class ResearchRunner:
    """
    Research-style analysis runner.
    
    Key features:
    1. Auto-start on upload (no buttons)
    2. Pause anytime (finishes current agent, then pauses)
    3. User can ask questions or add context while paused
    4. Resume continues exactly where it stopped
    5. Uses AutoGen lifecycle hooks (save_state, load_state, on_pause, on_resume)
    """
    
    def __init__(self, project_id: str, config: Optional[AnalysisConfig] = None):
        self.project_id = project_id
        self.project_dir = Path(f"data/projects/{project_id}")
        self.config = config if config else AnalysisConfig()
        
        # Run state storage
        self.runs_dir = self.project_dir / "runs"
        self.runs_dir.mkdir(exist_ok=True)
        
        # Current run
        self.current_run: Optional[AnalysisRun] = None
        
        # GraphFlow coordinator
        self.coordinator: Optional[GraphFlowCoordinator] = None
        
        # Pause control
        self._pause_requested = False
    
    async def start_new_run(self) -> AnalysisRun:
        """
        Start a new analysis run.
        Auto-triggered on ZIP upload.
        """
        # Create new run
        run = AnalysisRun(
            project_id=self.project_id,
            config=self.config.model_dump()
        )
        
        self.current_run = run
        self._save_run(run)
        
        print(f"🔬 Research Analysis Started: {run.run_id}")
        print(f"   Project: {self.project_id}")
        print(f"   Pipeline: {len(run.steps)} agents")
        
        # Initialize pause flag
        _pause_flags[run.run_id] = False
        
        # Start execution in background - store task to prevent cancellation
        task = asyncio.create_task(self._execute_pipeline())
        _running_tasks[run.run_id] = task
        
        # Clean up task when done
        def cleanup_task(t):
            _running_tasks.pop(run.run_id, None)
            _pause_flags.pop(run.run_id, None)
        task.add_done_callback(cleanup_task)
        
        return run
    
    async def _execute_pipeline(self):
        """
        Execute the agent pipeline using GraphFlowCoordinator.
        
        This runs asynchronously and can be paused at any time.
        Supports resuming from the next incomplete agent.
        """
        if not self.current_run:
            return
        
        run_id = self.current_run.run_id
        
        try:
            # Create GraphFlow coordinator
            print(f"🔬 Initializing GraphFlow coordinator...")
            self.coordinator = GraphFlowCoordinator(self.project_id, self.config)
            
            # Determine which agents need to run
            completed_steps = [step.agent_name for step in self.current_run.steps if step.status == "completed"]
            
            if completed_steps:
                print(f"📋 Resume mode: {len(completed_steps)} agents already completed")
                print(f"   Completed: {', '.join(completed_steps)}")
            
            print(f"▶️  Starting analysis pipeline...")
            
            # Build graph and task
            team = self._build_partial_graph(completed_steps)
            task = self._build_resume_task(completed_steps)
            
            # Map agent names to step indices
            agent_to_step = {
                'coordinator_agent': 0,
                'semantic_query_agent': 1,
                'best_practice_agent': 2,
                'sde_writer_agent': 3,
                'pm_writer_agent': 4,
                'qa_agent': 5
            }
            
            # Collect all messages
            result_messages = []
            
            # Run pipeline and save progress after each agent completes
            async for message in team.run_stream(task=task):
                # Check for pause request using global flag
                if _pause_flags.get(run_id, False):
                    print("⏸️  Pause request detected, stopping pipeline...")
                    self.current_run.pause()
                    self._save_run(self.current_run)
                    _pause_flags[run_id] = False
                    return
                
                result_messages.append(message)
                
                # Update progress when an agent completes
                if hasattr(message, 'source'):
                    agent_name = getattr(message, 'source', None)
                    content = getattr(message, 'content', None)
                    
                    if agent_name in agent_to_step and content:
                        step_index = agent_to_step[agent_name]
                        
                        # Extract basic output info
                        output_preview = {
                            "agent": agent_name,
                            "completed": True,
                            "content_preview": str(content)[:200] if content else "No content"
                        }
                        
                        # Mark step as completed
                        self.current_run.mark_step_completed(step_index, output_preview)
                        self._save_run(self.current_run)
                        print(f"   ✅ {agent_name} completed (progress saved)")
                        
                        # Check for pause after each agent completes using global flag
                        if _pause_flags.get(run_id, False):
                            print(f"⏸️  Pausing after {agent_name}...")
                            self.current_run.pause()
                            self._save_run(self.current_run)
                            _pause_flags[run_id] = False
                            return
            
            # Now parse all outputs using coordinator's parsing logic (from run_analysis)
            from app.models.schemas import CoordinatorOutput, SemanticQueryOutput, BestPracticeOutput, SDEOutput, PMOutput, QAOutput
            
            for msg in result_messages:
                content = msg.content if hasattr(msg, 'content') else str(msg)
                source = msg.source if hasattr(msg, 'source') else 'unknown'
                
                # Skip user messages and non-agent sources
                if source in ['user', 'unknown'] or not content or not content.strip():
                    continue
                
                try:
                    # Try to parse JSON from message
                    json_data = self.coordinator._extract_json(content)
                    step_index = agent_to_step.get(source)
                    
                    if step_index is not None:
                        # Update with fully parsed output
                        self.current_run.mark_step_completed(step_index, json_data)
                        
                except Exception as e:
                    print(f"   ⚠️  Failed to parse {source} output: {e}")
            
            # Save final state with all parsed outputs
            self._save_run(self.current_run)
            
            # Mark as completed
            self.current_run.complete()
            self._save_run(self.current_run)
            print(f"✅ Analysis COMPLETED: {self.current_run.run_id}")
        
        except Exception as e:
            print(f"❌ Pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            if self.current_run:
                self.current_run.status = RunStatus.FAILED
                self._save_run(self.current_run)
        """Build initial task with RAG context."""
        # Load project context
        context_file = self.project_dir / "context.json"
        with open(context_file, 'r') as f:
            context = json.load(f)
        
        # RAG search
        vector_store_path = str(self.project_dir / "vector_store")
        search_queries = [
            "main entrypoint application startup",
            "API routes endpoints handlers",
            "database models schemas",
        ]
        
        search_results = {}
        for query in search_queries:
            results = search_code(query, k=5, vector_store_path=vector_store_path)
            search_results[query] = results
        
        # Build task
        task = f"""🔬 **Research-Style Codebase Analysis**

**Project ID**: {self.project_id}

**Metadata**:
- Primary Language: {context.get('metadata', {}).get('primary_language', 'Unknown')}
- Total Files: {len(context.get('files', []))}
- Frameworks: {', '.join(context.get('metadata', {}).get('frameworks', []))}

**Initial Code Search**:
{json.dumps(search_results, indent=2)}

**Analysis Configuration**:
- Depth: {self.config.depth}
- Verbosity: {self.config.verbosity}
"""
        
        # Add user instructions if any
        if self.current_run and self.current_run.user_instructions:
            task += f"\n\n**User Instructions & Context**:\n"
            for i, instruction in enumerate(self.current_run.user_instructions, 1):
                task += f"{i}. {instruction}\n"
        
        return task
    
    def _build_partial_graph(self, completed_agents: List[str]):
        """
        Build a partial graph starting from the next incomplete agent.
        
        This allows resuming from a paused state without re-running completed agents.
        """
        from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
        from app.agents.coordinator_agent import create_coordinator_agent
        from app.agents.semantic_agent import create_semantic_query_agent
        from app.agents.best_practice_agent import create_best_practice_agent
        from app.agents.sde_writer_agent import create_sde_writer_agent
        from app.agents.pm_writer_agent import create_pm_writer_agent
        from app.agents.qa_agent import create_qa_agent
        
        # Create all agents
        agents_map = {
            'coordinator_agent': create_coordinator_agent(self.config),
            'semantic_query_agent': create_semantic_query_agent(self.config),
            'best_practice_agent': create_best_practice_agent(self.config),
            'sde_writer_agent': create_sde_writer_agent(self.config),
            'pm_writer_agent': create_pm_writer_agent(self.config),
            'qa_agent': create_qa_agent(self.config)
        }
        
        # Determine which agents to include in the graph
        agents_to_run = []
        for agent_name in ['coordinator_agent', 'semantic_query_agent', 'best_practice_agent', 
                           'sde_writer_agent', 'pm_writer_agent', 'qa_agent']:
            if agent_name not in completed_agents:
                agents_to_run.append(agent_name)
        
        print(f"   📝 Completed agents: {completed_agents}")
        print(f"   🎯 Agents to run: {agents_to_run}")
        
        # If all agents completed, return full graph (shouldn't happen but safety check)
        if not agents_to_run:
            print("   ⚠️  All agents already completed, building full graph")
            # Build full graph from scratch
            from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
            full_builder = DiGraphBuilder()
            for agent in agents_map.values():
                full_builder.add_node(agent)
            full_builder.set_entry_point(agents_map['coordinator_agent'])
            return GraphFlow(list(agents_map.values()), graph=full_builder.build())
        
        print(f"   🔧 Building partial graph for: {', '.join(agents_to_run)}")
        
        # Build partial graph based on what needs to run
        builder = DiGraphBuilder()
        
        # Original flow: coordinator → semantic → best_practice → (sde + pm) → qa
        # We need to maintain the dependencies
        
        if 'coordinator_agent' in agents_to_run:
            builder.add_node(agents_map['coordinator_agent'])
        if 'semantic_query_agent' in agents_to_run:
            builder.add_node(agents_map['semantic_query_agent'])
        if 'best_practice_agent' in agents_to_run:
            builder.add_node(agents_map['best_practice_agent'])
        if 'sde_writer_agent' in agents_to_run:
            builder.add_node(agents_map['sde_writer_agent'])
        if 'pm_writer_agent' in agents_to_run:
            builder.add_node(agents_map['pm_writer_agent'])
        if 'qa_agent' in agents_to_run:
            builder.add_node(agents_map['qa_agent'])
        
        # Add edges based on what's running
        if 'coordinator_agent' in agents_to_run and 'semantic_query_agent' in agents_to_run:
            builder.add_edge(agents_map['coordinator_agent'], agents_map['semantic_query_agent'])
            builder.set_entry_point(agents_map['coordinator_agent'])
        elif 'semantic_query_agent' in agents_to_run:
            builder.set_entry_point(agents_map['semantic_query_agent'])
        
        if 'semantic_query_agent' in agents_to_run and 'best_practice_agent' in agents_to_run:
            builder.add_edge(agents_map['semantic_query_agent'], agents_map['best_practice_agent'])
        elif 'best_practice_agent' in agents_to_run and 'semantic_query_agent' not in agents_to_run:
            builder.set_entry_point(agents_map['best_practice_agent'])
        
        if 'best_practice_agent' in agents_to_run:
            if 'sde_writer_agent' in agents_to_run:
                builder.add_edge(agents_map['best_practice_agent'], agents_map['sde_writer_agent'])
            if 'pm_writer_agent' in agents_to_run:
                builder.add_edge(agents_map['best_practice_agent'], agents_map['pm_writer_agent'])
        elif 'sde_writer_agent' in agents_to_run or 'pm_writer_agent' in agents_to_run:
            # If best_practice is done but sde/pm need to run, set them as entry points
            if 'sde_writer_agent' in agents_to_run:
                builder.set_entry_point(agents_map['sde_writer_agent'])
            if 'pm_writer_agent' in agents_to_run:
                builder.set_entry_point(agents_map['pm_writer_agent'])
        
        if 'qa_agent' in agents_to_run:
            if 'sde_writer_agent' in agents_to_run:
                builder.add_edge(agents_map['sde_writer_agent'], agents_map['qa_agent'])
            if 'pm_writer_agent' in agents_to_run:
                builder.add_edge(agents_map['pm_writer_agent'], agents_map['qa_agent'])
            # If both sde and pm are done, qa is the entry point
            if 'sde_writer_agent' not in agents_to_run and 'pm_writer_agent' not in agents_to_run:
                builder.set_entry_point(agents_map['qa_agent'])
        
        graph = builder.build()
        
        # Get agents in order - they're already the correct type (AssistantAgent extends ChatAgent)
        agents_list = [agents_map[name] for name in agents_to_run]
        
        team = GraphFlow(agents_list, graph=graph)
        return team
    
    def _build_resume_task(self, completed_agents: List[str]) -> str:
        """
        Build task for resuming, including context from completed agents.
        """
        # Load context
        context_path = self.project_dir / "context.json"
        if not context_path.exists():
            return "Resume analysis from paused state."
        
        with open(context_path, 'r') as f:
            context = json.load(f)
        
        # Build base task similar to _build_initial_task
        vector_store_path = str(self.project_dir / "vector_store")
        
        task = f"""🔬 **Resuming Codebase Analysis**

**Project ID**: {self.project_id}

**Metadata**:
- Primary Language: {context.get('metadata', {}).get('primary_language', 'Unknown')}
- Total Files: {len(context.get('files', []))}
- Frameworks: {', '.join(context.get('metadata', {}).get('frameworks', []))}

**Analysis Configuration**:
- Depth: {self.config.depth}
- Verbosity: {self.config.verbosity}
"""
        
        # Add results from completed agents
        if completed_agents and self.current_run:
            task += f"\n\n**Previous Analysis Results** (already completed):\n"
            for step in self.current_run.steps:
                if step.status == "completed" and step.output:
                    task += f"\n### {step.agent_name}:\n"
                    # Add a summary of the output
                    output_str = json.dumps(step.output, indent=2)
                    # Truncate if too long
                    if len(output_str) > 500:
                        output_str = output_str[:500] + "...\n(truncated)"
                    task += f"{output_str}\n"
            
            task += f"\n**Continue the analysis from where it was paused.**\n"
        
        return task
    
    def _save_run(self, run: AnalysisRun):
        """Save run state to disk."""
        run_file = self.runs_dir / f"{run.run_id}.json"
        with open(run_file, 'w') as f:
            json.dump(run.model_dump(), f, indent=2, default=str)
    
    def _load_run(self, run_id: str) -> AnalysisRun:
        """Load run state from disk."""
        run_file = self.runs_dir / f"{run_id}.json"
        with open(run_file, 'r') as f:
            data = json.load(f)
        return AnalysisRun(**data)
    
    async def pause(self):
        """
        Request pause.
        
        Current agent will finish, then pipeline pauses.
        """
        if not self.current_run or self.current_run.status != RunStatus.RUNNING:
            raise ValueError("No active run to pause")
        
        print("⏸️  Pause requested. Will pause after current agent completes...")
        # Set global pause flag so the running task can see it
        _pause_flags[self.current_run.run_id] = True
    
    async def resume(self, run_id: Optional[str] = None):
        """
        Resume from paused state.
        
        Uses load_state() and on_resume() lifecycle hooks.
        """
        if run_id:
            self.current_run = self._load_run(run_id)
        
        if not self.current_run:
            raise ValueError("No run to resume")
        
        if self.current_run.status != RunStatus.PAUSED:
            raise ValueError(f"Run is not paused (status: {self.current_run.status})")
        
        print(f"▶️  Resuming analysis: {self.current_run.run_id}")
        print(f"   Continuing from step {self.current_run.current_step + 1}/{len(self.current_run.steps)}")
        
        # Resume execution
        self.current_run.resume()
        self._save_run(self.current_run)
        
        # Reset pause flag
        run_id = self.current_run.run_id
        _pause_flags[run_id] = False
        
        # Start execution in background - store task to prevent cancellation
        task = asyncio.create_task(self._execute_pipeline())
        _running_tasks[run_id] = task
        
        # Clean up task when done
        def cleanup_task(t):
            _running_tasks.pop(run_id, None)
            _pause_flags.pop(run_id, None)
        task.add_done_callback(cleanup_task)
    
    async def ask_question(self, question: str) -> str:
        """
        Answer user question about current analysis.
        
        Available while paused or running.
        """
        if not self.current_run:
            return "No active analysis run."
        
        # Get current status
        current_agent = self.current_run.get_current_agent()
        completed_steps = sum(1 for step in self.current_run.steps if step.status == "completed")
        
        # Simple question routing
        question_lower = question.lower()
        
        if "analyzing" in question_lower or "working on" in question_lower:
            if current_agent:
                answer = f"Currently analyzing with: **{current_agent}**\n\nProgress: {completed_steps}/{len(self.current_run.steps)} agents completed ({self.current_run.progress_percent:.1f}%)"
            else:
                answer = "Analysis is complete or not started."
        
        elif "progress" in question_lower or "status" in question_lower:
            answer = f"""**Analysis Progress**:
- Status: {self.current_run.status.value}
- Current Step: {current_agent or 'Complete'}
- Progress: {self.current_run.progress_percent:.1f}% ({completed_steps}/{len(self.current_run.steps)} agents)
- Started: {self.current_run.started_at.strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        elif "results" in question_lower or "found" in question_lower:
            # Show intermediate results
            answer = f"**Intermediate Outputs**:\n\n"
            for agent_name, output in self.current_run.intermediate_outputs.items():
                answer += f"**{agent_name}**:\n{json.dumps(output, indent=2)}\n\n"
        
        else:
            # RAG search for specific questions
            vector_store_path = str(self.project_dir / "vector_store")
            
            try:
                results = search_code(question, k=3, vector_store_path=vector_store_path)
                
                if results and len(results) > 0:
                    answer = f"**Search Results for '{question}'**:\n\n"
                    for i, result in enumerate(results, 1):
                        file_path = result.get('file_path', 'Unknown')
                        content = result.get('content', '')
                        language = result.get('language', '')
                        
                        answer += f"{i}. **{file_path}**"
                        if language:
                            answer += f" ({language})"
                        answer += "\n"
                        answer += f"```{language.lower() if language else ''}\n{content}\n```\n\n"
                else:
                    answer = f"No results found for '{question}'. The codebase has been indexed and searchable."
            except Exception as e:
                answer = f"Error searching codebase: {str(e)}. Please try rephrasing your question."
        
        # Log question and answer
        self.current_run.add_user_question(question, answer)
        self._save_run(self.current_run)
        
        return answer
    
    async def add_user_context(self, instruction: str):
        """
        Add user instruction/context.
        
        This will be injected into the pipeline on next resume.
        """
        if not self.current_run:
            raise ValueError("No active run")
        
        self.current_run.add_user_instruction(instruction)
        self._save_run(self.current_run)
        
        print(f"💬 User instruction added: {instruction[:50]}...")
    
    def get_run_summary(self) -> Dict[str, Any]:
        """Get current run summary."""
        if not self.current_run:
            return {"status": "no_active_run"}
        
        return self.current_run.get_summary()
    
    def get_latest_run_id(self) -> Optional[str]:
        """Get the latest run ID for this project."""
        run_files = list(self.runs_dir.glob("*.json"))
        if not run_files:
            return None
        
        # Sort by modification time
        latest = max(run_files, key=lambda p: p.stat().st_mtime)
        return latest.stem
