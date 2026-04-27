from __future__ import annotations


from modules.outline_content_prompt_catalog import (
    build_agent1_outline_prompts,
    build_agent2_semantic_prompts,
    build_agent3_micro_brief_prompts,
    build_context_vector_prompts,
    build_k2q_prompts,
    build_outline_skill_reference_block,
    build_outline_synthesis_block,
    build_query_cluster_prompts,
    build_semantic_enforcer_block,
    build_writer_brief_block,
)


def _assert_rtcfe_shape(text: str) -> None:
    assert "ROLE" in text
    assert "TASK" in text
    assert "CONTEXT" in text
    assert "FORMAT" in text
    assert "EXAMPLE" in text


def test_prompt_catalog_blocks_follow_role_task_context_format_example_shape() -> None:
    prompts = [
        build_outline_skill_reference_block(),
        build_outline_synthesis_block("Informational"),
        build_semantic_enforcer_block(),
        build_writer_brief_block(),
    ]
    for prompt in prompts:
        _assert_rtcfe_shape(prompt)


def test_runtime_prompts_no_longer_emit_github_reference_style_copy() -> None:
    system_a, user_a = build_k2q_prompts("hang hoa phai sinh la gi", "Hang hoa phai sinh", "ky quy, hop dong")
    system_b, user_b = build_query_cluster_prompts("Hang hoa phai sinh", ["hang hoa phai sinh", "ky quy hang hoa"])
    system_c, user_c = build_context_vector_prompts("hang hoa phai sinh la gi", "H2: Tong quan\nH3: Dinh nghia")

    for prompt in (system_a, user_a, system_b, user_b, system_c, user_c):
        _assert_rtcfe_shape(prompt)
        assert "GITHUB OUTLINE-CONTENT WORKFLOW REFERENCE" not in prompt
        assert "following the GitHub outline-content workflow" not in prompt


def test_k2q_prompt_keeps_json_schema_and_example() -> None:
    system_prompt, user_prompt = build_k2q_prompts(
        "hang hoa phai sinh la gi",
        "Hang hoa phai sinh",
        "ky quy, hop dong, thanh toan",
    )

    assert '"questions"' in system_prompt
    assert "Focus keyword: hang hoa phai sinh la gi" in user_prompt
    assert '{"questions": [' in system_prompt


def test_agent_prompt_builders_follow_role_task_context_format_example_shape() -> None:
    agent1_system, agent1_user = build_agent1_outline_prompts(
        topic="hang hoa phai sinh la gi",
        intent_label="Informational",
        methodology_prompt="Koray-style semantic flow",
        semantic_context="EAV rows, consensus, and gap map",
        competitor_inputs="PAA, headings, and n-grams",
    )
    agent2_system, agent2_user = build_agent2_semantic_prompts(
        entity="Hang hoa phai sinh",
        intent_label="Informational",
        vectors_text="- definition before mechanism",
        headings_json='[{"level":"H2","text":"[MAIN] Tong quan"}]',
        input_h2_count=1,
        input_h3_count=0,
    )
    agent3_system, agent3_user = build_agent3_micro_brief_prompts(
        topic="hang hoa phai sinh la gi",
        entity="Hang hoa phai sinh",
        intent_label="Informational",
        niche="finance",
        methodology_prompt="Koray-style semantic flow",
        prompt_pack_text="Fact pack and section context map",
        input_package_text="Locked outline and research package",
    )

    for prompt in (
        agent1_system,
        agent1_user,
        agent2_system,
        agent2_user,
        agent3_system,
        agent3_user,
    ):
        _assert_rtcfe_shape(prompt)
