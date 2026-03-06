import asyncio
from graph import app_graph, PodcastState

async def test_run():
    state = PodcastState(
        topic="The history of the pencil",
        tone="educational",
        audience="general",
        target_words=300,
        target_minutes=2,
        constraints="",
        current_status="init",
        search_queries=[],
        sources=[],
        script_segments=[],
        episode_title="",
        tts_results={},
        final_assembly={},
        errors=[],
        dry_run=True, # Doing a dry run to avoid calling LLM or text-to-speech APIs
        multi_voice=False
    )
    
    print("Starting graph execution with a dry run...")
    async for step_result in app_graph.astream(state, stream_mode="updates"):
        for node_name, state_update in step_result.items():
            print(f"Node [{node_name}] -> Status: {state_update.get('current_status', '')}")
            
if __name__ == "__main__":
    asyncio.run(test_run())
