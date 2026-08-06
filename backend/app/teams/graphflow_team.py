"""
Analysis Coordinator using AutoGen 0.7.5 GraphFlow
Orchestrates 6-agent pipeline with directed graph workflow
"""

from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken
from typing import Dict, Any, Optional, List
import json
import time
from pathlib import Path

from app.agents.coordinator_agent import create_coordinator_agent
from app.agents.semantic_agent import create_semantic_query_agent
from app.agents.best_practice_agent import create_best_practice_agent
from app.agents.sde_writer_agent import create_sde_writer_agent
from app.agents.pm_writer_agent import create_pm_writer_agent
from app.agents.qa_agent import create_qa_agent
from app.agents.utils import search_code
from app.models.schemas import (
    CoordinatorOutput,
    SemanticQueryOutput,
    BestPracticeOutput,
    SDEOutput,
    PMOutput,
    QAOutput,
    AnalysisResult
)
from app.config.analysis_config import AnalysisConfig, load_config


class GraphFlowCoordinator:
    
    def __init__(self, project_id: str, config: Optional[AnalysisConfig] = None, project_dir: Optional[Path] = None):
        """
        Initialize the coordinator.
        
        Args:
            project_id: UUID of the project to analyze
            config: Optional analysis config (will load from file if None)
            project_dir: Optional absolute path to project directory (for deployment flexibility)
        """
        self.project_id = project_id
        # Use provided path or default relative path
        self.project_dir = project_dir if project_dir else Path(f"data/projects/{project_id}")
        
        # Load or use provided config
        self.config = config if config else load_config(project_id)
        
        # Load project context
        self.project_context = self._load_project_context()
        
        # Vector store path
        self.vector_store_path = str(self.project_dir / "vector_store")
        
        # Results storage
        self.results: Dict[str, Any] = {}
        self.errors: list[str] = []
        
        # Persona filtering (for user-selected reports)
        self.selected_personas: List[str] = ["SDE", "PM"]  # Default: both
        
        # Status callback for real-time updates (callable or None)
        self.status_callback = None  # type: ignore
        
    def _load_project_context(self) -> Dict[str, Any]:
        """Load the preprocessed project context"""
        context_file = self.project_dir / "context.json"
        
        if not context_file.exists():
            raise FileNotFoundError(
                f"Project context not found. "
                f"Run preprocessing first for project {self.project_id}"
            )
        
        with open(context_file, 'r') as f:
            return json.load(f)
    
    def _build_graph(self):
        """
        Build the directed graph for the analysis workflow.
        
        Flow:
        Coordinator → Semantic → Best Practice → (SDE + PM) → QA
        (Conditionally includes SDE and/or PM based on selected_personas)
        """
        # Create all agents
        coordinator = create_coordinator_agent(self.config)
        semantic_agent = create_semantic_query_agent(self.config)
        best_practice_agent = create_best_practice_agent(self.config)
        qa_agent = create_qa_agent(self.config)
        
        # Build the directed graph
        builder = DiGraphBuilder()
        
        # Add core nodes (always present)
        builder.add_node(coordinator)
        builder.add_node(semantic_agent)
        builder.add_node(best_practice_agent)
        builder.add_node(qa_agent)
        
        # Sequential flow: Coordinator → Semantic → Best Practice
        builder.add_edge(coordinator, semantic_agent)
        builder.add_edge(semantic_agent, best_practice_agent)
        
        # Conditionally add writer agents based on selected personas
        writer_agents = []
        sde_writer = None
        pm_writer = None
        
        if "SDE" in self.selected_personas:
            sde_writer = create_sde_writer_agent(self.config)
            builder.add_node(sde_writer)
            builder.add_edge(best_practice_agent, sde_writer)
            builder.add_edge(sde_writer, qa_agent)
            writer_agents.append("SDE")
        
        if "PM" in self.selected_personas:
            pm_writer = create_pm_writer_agent(self.config)
            builder.add_node(pm_writer)
            builder.add_edge(best_practice_agent, pm_writer)
            builder.add_edge(pm_writer, qa_agent)
            writer_agents.append("PM")
        
        # If no writers selected, connect Best Practice directly to QA
        if not writer_agents:
            builder.add_edge(best_practice_agent, qa_agent)
        
        print(f"   Building graph with writers: {', '.join(writer_agents) if writer_agents else 'None'}")
        
        # Set entry point
        builder.set_entry_point(coordinator)
        
        # Build and validate
        graph = builder.build()
        
        # Build list of all agents that were actually added
        all_agents = [coordinator, semantic_agent, best_practice_agent]
        if "SDE" in self.selected_personas and sde_writer is not None:
            all_agents.append(sde_writer)
        if "PM" in self.selected_personas and pm_writer is not None:
            all_agents.append(pm_writer)
        all_agents.append(qa_agent)
        
        # Create GraphFlow team with only the agents we added
        team = GraphFlow(
            all_agents,  # type: ignore
            graph=graph
        )
        
        return team
    
    def _build_initial_task(self) -> str:
        """Build the initial task prompt for the coordinator agent"""
        
        # Perform initial vector searches
        search_queries = [
            "main entrypoint application startup",
            "API routes endpoints handlers",
            "database models schemas entities",
            "configuration settings environment"
        ]
        
        search_results = {}
        for query in search_queries:
            results = search_code(
                query,
                k=5,
                vector_store_path=self.vector_store_path
            )
            search_results[query] = results
        
        task = f"""Analyze this codebase project:

**Project ID**: {self.project_id}

**Analysis Configuration**:
- Selected Reports: {', '.join(self.selected_personas)}
- Analysis Depth: {self.config.depth}
- Verbosity: {self.config.verbosity}

**Project Metadata**:
- Primary Language: {self.project_context.get('metadata', {}).get('primary_language', 'Unknown')}
- Total Files: {len(self.project_context.get('files', []))}
- Frameworks: {', '.join(self.project_context.get('metadata', {}).get('frameworks', []))}

**Initial Code Search Results**:
{json.dumps(search_results, indent=2)}

**Analysis Configuration**:
- Depth: {self.config.depth}
- Verbosity: {self.config.verbosity}
- Features Enabled: {self.config.features_enabled.model_dump()}

Coordinate a comprehensive codebase analysis through the pipeline."""
        
        return task
    
    async def run_analysis(self) -> AnalysisResult:
        """
        Execute the GraphFlow analysis pipeline.
        
        Returns:
            AnalysisResult with all agent outputs
        """
        start_time = time.time()
        
        print(f"🚀 Starting GraphFlow analysis for project {self.project_id}")
        print(f"   Config: {self.config.depth} depth, {self.config.verbosity} verbosity")
        print(f"   Features: {self.config.features_enabled.model_dump()}")
        
        try:
            # Build the graph
            team = self._build_graph()
            
            # Build initial task
            task = self._build_initial_task()
            
            print("\n📊 Executing GraphFlow pipeline...")
            print("   Coordinator → Semantic → Best Practice → (SDE + PM) → QA")
            
            # Run the workflow
            result_messages = []
            last_source = None
            
            async for message in team.run_stream(task=task):
                # Collect all messages from the workflow
                result_messages.append(message)
                
                # Log when each agent starts (detect source change)
                if hasattr(message, 'source'):
                    current_source = message.source
                    if current_source != last_source and current_source not in ['user', 'unknown']:
                        agent_name = current_source.replace('_', ' ').title()
                        print(f"   🔄 {agent_name} started...")
                        
                        # Update status for frontend
                        if self.status_callback:
                            if current_source == 'coordinator_agent':
                                self.status_callback("Planning analysis strategy...", 10)
                            elif current_source == 'semantic_query_agent':
                                self.status_callback("Analyzing code structure...", 25)
                            elif current_source == 'best_practice_agent':
                                self.status_callback("Searching for best practices...", 40)
                            elif current_source == 'sde_writer_agent':
                                self.status_callback("Generating technical documentation...", 60)
                            elif current_source == 'pm_writer_agent':
                                self.status_callback("Creating product documentation...", 60)
                            elif current_source == 'qa_agent':
                                self.status_callback("Validating analysis quality...", 85)
                        
                        last_source = current_source
            
            # Extract outputs from messages
            coordinator_output = None
            semantic_output = None
            best_practice_output = None
            sde_output = None
            pm_output = None
            qa_output = None
            
            for msg in result_messages:
                content = msg.content if hasattr(msg, 'content') else str(msg)
                source = msg.source if hasattr(msg, 'source') else 'unknown'
                
                # Skip user messages and non-agent sources
                if source in ['user', 'unknown']:
                    continue
                
                # Skip empty messages
                if not content or not content.strip():
                    continue
                
                try:
                    # Try to parse JSON from message
                    json_data = self._extract_json(content)
                    
                    if source == 'coordinator_agent':
                        print(f"   ✅ Coordinator Agent completed")
                        coordinator_output = CoordinatorOutput(**json_data)
                        self.results['coordinator'] = coordinator_output.model_dump()
                    elif source == 'semantic_query_agent':
                        print(f"   ✅ Semantic Query Agent completed")
                        semantic_output = SemanticQueryOutput(**json_data)
                        self.results['semantic'] = semantic_output.model_dump()
                    elif source == 'best_practice_agent':
                        print(f"   ✅ Best Practice Agent completed")
                        best_practice_output = BestPracticeOutput(**json_data)
                        self.results['best_practices'] = best_practice_output.model_dump()
                    elif source == 'sde_writer_agent':
                        print(f"   ✅ SDE Writer Agent completed")
                        sde_output = SDEOutput(**json_data)
                        self.results['sde'] = sde_output.model_dump()
                    elif source == 'pm_writer_agent':
                        print(f"   ✅ PM Writer Agent completed")
                        pm_output = PMOutput(**json_data)
                        self.results['pm'] = pm_output.model_dump()
                    elif source == 'qa_agent':
                        print(f"   ✅ QA Agent completed")
                        qa_output = QAOutput(**json_data)
                        self.results['qa'] = qa_output.model_dump()
                    else:
                        print(f"   ⚠️  Unknown agent source: {source}")
                        
                except Exception as e:
                    error_detail = f"Failed to parse {source} output: {str(e)}"
                    self.errors.append(error_detail)
                    print(f"   ⚠️  {error_detail}")
            
            # Calculate execution time
            execution_time = time.time() - start_time
            
            # Build final result
            result = AnalysisResult(
                project_id=self.project_id,
                config_used=self.config.model_dump(),
                coordinator_output=coordinator_output,
                semantic_analysis=semantic_output,
                best_practices=best_practice_output,
                sde_report=sde_output,
                pm_report=pm_output,
                qa_report=qa_output,
                agent_results=self.results,
                execution_time_seconds=round(execution_time, 2),
                success=len(self.errors) == 0,
                errors=self.errors
            )
            
            # Save result
            self._save_result(result)
            
            print(f"\n✅ GraphFlow analysis complete in {execution_time:.2f}s")
            if self.errors:
                print(f"⚠️  {len(self.errors)} errors occurred")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"GraphFlow analysis failed: {str(e)}"
            self.errors.append(error_msg)
            
            print(f"\n❌ {error_msg}")
            
            return AnalysisResult(
                project_id=self.project_id,
                config_used=self.config.model_dump(),
                agent_results=self.results,
                execution_time_seconds=round(execution_time, 2),
                success=False,
                errors=self.errors
            )
    
    def _extract_json(self, content: str) -> Dict[str, Any]:
        """
        Extract JSON from agent response.
        
        Agents may wrap JSON in markdown code blocks or add text.
        """
        if not content or not isinstance(content, str):
            raise ValueError("Content is empty or not a string")
        
        content = content.strip()
        
        # Try direct parse first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Look for JSON in code blocks
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
        
        if "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                json_str = content[start:end].strip()
                # Remove language identifier if present (e.g., "json\n{...}")
                if json_str.startswith(('json', 'JSON')):
                    json_str = json_str[4:].strip()
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
        
        # Try to find JSON object (look for balanced braces)
        start = content.find("{")
        if start != -1:
            # Find matching closing brace
            brace_count = 0
            end = start
            for i in range(start, len(content)):
                if content[i] == '{':
                    brace_count += 1
                elif content[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            
            if end > start:
                json_str = content[start:end]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
        
        raise ValueError(f"No valid JSON found in content (first 200 chars): {content[:200]}")
    
    def _save_result(self, result: AnalysisResult):
        """Save analysis result to file"""
        output_file = self.project_dir / "analysis_result.json"
        with open(output_file, 'w') as f:
            json.dump(result.model_dump(), f, indent=2)
        print(f"\n💾 Results saved to {output_file}")


# ============================================================================
# Convenience Functions (Backward Compatible)
# ============================================================================

async def run_analysis_pipeline(
    project_id: str,
    config: Optional[AnalysisConfig] = None
) -> AnalysisResult:
    """
    Run the GraphFlow analysis pipeline for a project.
    
    Args:
        project_id: Project UUID
        config: Optional analysis configuration
        
    Returns:
        AnalysisResult with all outputs
    """
    coordinator = GraphFlowCoordinator(project_id, config)
    return await coordinator.run_analysis()
