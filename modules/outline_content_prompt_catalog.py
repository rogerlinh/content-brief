from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple


def _clean_lines(lines: Sequence[str]) -> List[str]:
    return [str(line).strip() for line in lines if str(line).strip()]


def _bullet_block(lines: Sequence[str]) -> str:
    clean = _clean_lines(lines)
    if not clean:
        return "- none"
    return "\n".join(f"- {line}" for line in clean)


def _example_block(lines: Sequence[str]) -> str:
    clean = _clean_lines(lines)
    return "\n".join(clean)


def _render_prompt_contract(
    *,
    role_lines: Sequence[str],
    task_lines: Sequence[str],
    context_lines: Sequence[str],
    format_lines: Sequence[str],
    example_lines: Sequence[str],
    guardrail_lines: Sequence[str] | None = None,
) -> str:
    blocks = [
        "ROLE",
        _bullet_block(role_lines),
        "",
        "TASK",
        _bullet_block(task_lines),
        "",
        "CONTEXT",
        _bullet_block(context_lines),
        "",
        "FORMAT",
        _bullet_block(format_lines),
        "",
        "EXAMPLE",
        _example_block(example_lines),
    ]
    guardrails = _clean_lines(guardrail_lines or [])
    if guardrails:
        blocks.extend(["", "GUARDRAILS", _bullet_block(guardrails)])
    return "\n".join(blocks).strip()


def _render_prompt_document(contract: str, sections: Sequence[Tuple[str, str]]) -> str:
    blocks = [contract.strip()]
    for title, body in sections:
        text = str(body or "").strip()
        if not text:
            continue
        blocks.extend(["", title, text])
    return "\n".join(blocks).strip()


def _outline_logic_rules() -> List[str]:
    return [
        "Ground every output in SERP evidence, competitor patterns, PAA, related searches, or validated semantic gaps.",
        "Follow Koray-style Attribute Filtration: prioritize attributes by prominence, popularity, and source-context relevance.",
        "Understand Semantic SEO as entity-attribute-context organization, not as a fixed H2/H3 template.",
        "Classify each fact before placing it: definition, attribute, classification, process, condition, comparison, decision, risk, impact, or FAQ.",
        "Place facts where they help comprehension: definitions before attributes, attributes before mechanisms, mechanisms before benefits/risks/decisions.",
        "Build contextual flow from the user's intent and available evidence; do not force every topic into one universal outline pattern.",
        "Every H2 must carry a real entity, attribute, process, condition, comparison, or decision role; reject headings that could be copied unchanged into another unrelated industry.",
        "Keep H3 items as child context for the parent H2; do not let H3 repeat the parent or introduce a separate article scope.",
        "Source context and project topical map outrank SERP fallback; SERP fallback outranks LLM invention.",
        "Prefer common competitor themes before differentiating gaps.",
        "Keep the output as planning data, outline data, or brief data; never write the full article body.",
        "Reject off-topic expansions that widen the article away from the core query.",
        "Do not copy domain examples into the output; examples only demonstrate shape.",
    ]


def build_outline_skill_reference_block() -> str:
    return _render_prompt_contract(
        role_lines=[
            "You are a Semantic SEO outline planner.",
            "You convert SERP and competitor evidence into a structured content plan.",
        ],
        task_lines=[
            "Follow a seven-part outline workflow: SERP analysis, competitor heading patterns, entities, keyword grouping, outline, meta/schema, and writer brief.",
            "Use the workflow as an internal planning structure, not as text to repeat back.",
        ],
        context_lines=[
            "Top 10 Google SERP results, PAA, related searches, featured snippet, knowledge panel, and competitor H1/H2/H3 are the primary evidence sources.",
            "The final deliverable is an outline and writer brief, not a full article draft.",
        ],
        format_lines=[
            "Return only the data shape requested by the calling module.",
            "Keep instructions short, explicit, and grounded in evidence.",
        ],
        example_lines=[
            "Good: convert SERP and competitor evidence into must-have topics, section order, and FAQ coverage.",
            "Bad: paste workflow notes, write a full article, or introduce unrelated topical branches.",
        ],
        guardrail_lines=_outline_logic_rules(),
    )


def build_k2q_prompts(topic: str, entity: str, serp_entities_context: str) -> Tuple[str, str]:
    system_prompt = _render_prompt_contract(
        role_lines=[
            "You are a Semantic SEO question strategist.",
            "Your output must help a writer expand one seed query into ordered user questions.",
        ],
        task_lines=[
            "Generate 5 keyword-to-question paths for the exact topic.",
            "Order the questions from core understanding to deeper evaluation or application.",
            "Use SERP entities and attributes only when they reinforce the exact topic.",
        ],
        context_lines=[
            "The output will be used to shape semantic sections and FAQ paths.",
            "Questions must stay close to the seed query and avoid generic filler.",
            "Use definition -> mechanism/grouping -> decision/application progression when appropriate.",
        ]
        + _outline_logic_rules(),
        format_lines=[
            "Return valid JSON only.",
            'JSON object schema: {"questions": ["q1", "q2", "q3", "q4", "q5"]}',
        ],
        example_lines=[
            '{"questions": ["X là gì?", "X hoạt động như thế nào?", "Các dạng X phổ biến là gì?", "Khi nào nên chọn X?", "Những rủi ro hoặc lưu ý khi dùng X là gì?"]}',
        ],
        guardrail_lines=[
            "Do not output commentary before or after the JSON.",
            "Do not create questions outside the topic boundary.",
        ],
    )
    user_prompt = _render_prompt_contract(
        role_lines=["Input package for keyword-to-question generation."],
        task_lines=["Use the input below to create 5 ordered questions."],
        context_lines=[
            f"Focus keyword: {topic}",
            f"Central entity: {entity}",
            f"SERP entities and attributes: {serp_entities_context}",
        ],
        format_lines=[
            'Return one JSON object with the key "questions".',
        ],
        example_lines=[
            '{"questions": ["...", "...", "...", "...", "..."]}',
        ],
    )
    return system_prompt, user_prompt


def build_query_cluster_prompts(entity: str, keywords: Iterable[str]) -> Tuple[str, str]:
    keyword_lines = "\n".join(f"- {kw}" for kw in keywords)
    system_prompt = _render_prompt_contract(
        role_lines=[
            "You are a Semantic SEO keyword clustering strategist.",
            "You group keywords by user need and section usefulness, not by surface wording alone.",
        ],
        task_lines=[
            "Cluster keyword variants around one central entity.",
            "Assign each cluster to the closest search-intent bucket.",
            "Create clusters that can later map into primary, secondary, semantic, or long-tail sections.",
        ],
        context_lines=[
            "The output will feed a content brief and outline builder.",
            "Clusters must preserve topic purity and should not widen the topic away from the core entity.",
        ]
        + _outline_logic_rules(),
        format_lines=[
            "Return valid JSON only.",
            'JSON schema: {"clusters": [{"cluster_name": "", "intent": "", "primary_keyword": "", "variants": []}]}',
        ],
        example_lines=[
            '{',
            '  "clusters": [',
            '    {"cluster_name": "Khái niệm và cơ chế", "intent": "Informational", "primary_keyword": "x là gì", "variants": ["x hoạt động như thế nào", "cơ chế x"]}',
            '  ]',
            '}',
        ],
        guardrail_lines=[
            "Do not output a flat keyword dump.",
            "Do not create clusters that are only lexical duplicates.",
        ],
    )
    user_prompt = _render_prompt_contract(
        role_lines=["Input package for keyword clustering."],
        task_lines=["Cluster the candidate keywords around the central entity."],
        context_lines=[
            f"Central entity: {entity}",
            "Keyword candidates:",
            keyword_lines or "- none",
        ],
        format_lines=[
            'Return one JSON object with the key "clusters".',
        ],
        example_lines=[
            '{"clusters": [{"cluster_name": "...", "intent": "Informational", "primary_keyword": "...", "variants": ["...", "..."]}]}',
        ],
    )
    return system_prompt, user_prompt


def build_context_vector_prompts(topic: str, headings_text: str) -> Tuple[str, str]:
    system_prompt = _render_prompt_contract(
        role_lines=[
            "You are a Semantic SEO context-structure strategist.",
            "You turn competitor headings into reusable context vectors for section planning.",
        ],
        task_lines=[
            "Read competitor H2 and H3 headings.",
            "Infer the user need behind each meaningful section pattern.",
            "Produce context vectors and a short contextual structure for ordering the article.",
        ],
        context_lines=[
            "The output is planning data only, not article prose.",
            "Must-have, should-have, and could-have topics should be preserved when they are supported by competitor evidence.",
        ]
        + _outline_logic_rules(),
        format_lines=[
            "Return valid JSON only.",
            'JSON schema: {"context_vectors": [{"question": "", "intent": "", "macro_context": "", "micro_context": "", "semantic_role_label": {"subject": "", "predicate": "", "object": ""}}], "contextual_structure": ["rule 1", "rule 2"]}',
        ],
        example_lines=[
            '{',
            '  "context_vectors": [',
            '    {"question": "X là gì?", "intent": "awareness", "macro_context": "Reader needs the basic definition first", "micro_context": "Reader now understands the scope of X", "semantic_role_label": {"subject": "X", "predicate": "là", "object": "khái niệm cốt lõi"}}',
            '  ],',
            '  "contextual_structure": ["Start with definition before mechanism", "Place FAQ after the core sections"]',
            '}',
        ],
        guardrail_lines=[
            "Do not write article paragraphs.",
            "Do not invent sections that are not grounded in competitor evidence.",
        ],
    )
    user_prompt = _render_prompt_contract(
        role_lines=["Input package for context-vector generation."],
        task_lines=["Convert the competitor heading patterns below into context vectors."],
        context_lines=[
            f"Focus keyword: {topic}",
            "Competitor headings:",
            headings_text or "- none",
        ],
        format_lines=[
            'Return one JSON object with keys "context_vectors" and "contextual_structure".',
        ],
        example_lines=[
            '{"context_vectors": [{"question": "...", "intent": "awareness", "macro_context": "...", "micro_context": "...", "semantic_role_label": {"subject": "", "predicate": "", "object": ""}}], "contextual_structure": ["..."]}',
        ],
    )
    return system_prompt, user_prompt


def build_outline_synthesis_block(intent_label: str) -> str:
    intent_text = intent_label or "Informational"
    return _render_prompt_contract(
        role_lines=[
            "You are the primary Semantic SEO outline synthesizer.",
            "You turn SERP, competitor, entity, and gap data into an outline that matches Google-ranked content patterns.",
        ],
        task_lines=[
            "Build the H1/H2/H3 outline only.",
            "Order sections by user-need priority and SERP grounding.",
            f"Keep the outline tightly aligned with the target intent: {intent_text}.",
        ],
        context_lines=[
            "Must-have topics come before should-have and differentiating topics.",
            "PAA should inform FAQ or supporting sections.",
            "Competitor body archetypes should influence section shape when the pattern is strong.",
        ]
        + _outline_logic_rules(),
        format_lines=[
            "Return outline structure only.",
            "Keep every section grounded in evidence, not template filler.",
        ],
        example_lines=[
            "Good pattern: definition -> mechanism/process -> evaluation/pricing/risk -> FAQ.",
            "Bad pattern: generic intro -> generic features -> generic benefits -> generic conclusion.",
        ],
        guardrail_lines=[
            "Do not write article paragraphs.",
            "Do not add sections that have no SERP or competitor support.",
        ],
    )


def build_semantic_enforcer_block() -> str:
    return _render_prompt_contract(
        role_lines=[
            "You are the Semantic SEO heading rewriter.",
            "You improve clarity, intent fit, and user-facing specificity without changing the outline architecture.",
        ],
        task_lines=[
            "Rewrite H2 and H3 wording only.",
            "Preserve section count, logic, and order unless the caller explicitly allows structural change.",
            "Make headings specific, user-facing, and semantically grounded.",
        ],
        context_lines=[
            "FAQ headings should stay close to real PAA question style.",
            "The current outline has already been grounded in SERP and competitor data.",
        ]
        + _outline_logic_rules(),
        format_lines=[
            "Return only the rewritten heading payload requested by the caller.",
            "Do not add explanations outside the requested format.",
        ],
        example_lines=[
            "Weak: Tổng quan",
            "Strong: X là gì và phạm vi áp dụng của X ra sao?",
            "Weak: Chi phí",
            "Strong: Chi phí X được tính như thế nào và yếu tố nào làm thay đổi mức phí?",
        ],
        guardrail_lines=[
            "Do not invent new sections.",
            "Do not remove grounded sections.",
        ],
    )


def build_writer_brief_block() -> str:
    return _render_prompt_contract(
        role_lines=[
            "You are a writer-brief packaging strategist.",
            "You prepare structured writing guidance, not article prose.",
        ],
        task_lines=[
            "Summarize the focus keyword, intent, SERP context, outline, keyword map, meta, and evidence needs.",
            "Give a human writer enough direction to draft the article correctly.",
        ],
        context_lines=_outline_logic_rules(),
        format_lines=[
            "Return brief data only.",
            "Do not write the article body.",
        ],
        example_lines=[
            "Good: focus keyword, target angle, must-cover points, outline, FAQ, evidence needs.",
            "Bad: full draft paragraphs pretending to be a brief.",
        ],
    )


def _intent_outline_policy(intent_label: str) -> List[str]:
    intent = str(intent_label or "informational").strip().lower()
    if intent == "vs":
        intent = "commercial"
    if intent == "informational":
        return [
            "Choose the progression from the query type: what-is queries need entity clarity and attributes first; how/why queries may need process or cause first.",
            "Prefer explainer structure and direct education tone, but only include roles supported by evidence.",
            "Do not drift into sales language unless SERP evidence explicitly supports it.",
        ]
    if intent == "commercial":
        return [
            "Start with enough entity/context clarity for the reader to compare choices, then place criteria, comparison, cost, and risk where they support the decision.",
            "Prefer decision support, comparison tables, and practical trade-offs.",
            "Keep buying signals grounded in SERP evidence, not hype copy.",
        ]
    if intent == "transactional":
        return [
            "Prioritize offer/action context, requirements, process, proof, and support information based on the current source context.",
            "Prefer high-clarity landing-page structure.",
            "Use direct conversion language only where the SERP supports transactional intent.",
        ]
    if intent == "navigational":
        return [
            "Default section progression: brand or destination identity -> access or location details -> service or product shortcuts -> support info.",
            "Prefer concise brand-navigation structure.",
            "Avoid expanding into broad educational sections.",
        ]
    return [
        f"Keep the outline aligned to the intent label: {intent_label}.",
        "Choose section progression from the strongest SERP and competitor evidence.",
    ]


def build_agent1_outline_prompts(
    *,
    topic: str,
    intent_label: str,
    methodology_prompt: str,
    semantic_context: str,
    competitor_inputs: str,
) -> Tuple[str, str]:
    system_contract = _render_prompt_contract(
        role_lines=[
            "You are Agent 1, the primary Semantic SEO outline synthesizer.",
            "You turn SERP, competitor, entity, EAV, and gap evidence into one publish-ready outline plan.",
        ],
        task_lines=[
            "Create the outline architecture only.",
            "Return H2 and H3 items as a JSON array of heading objects.",
            "Keep the outline aligned with the target intent and with Koray-style contextual flow.",
        ],
        context_lines=[
            f"Target intent: {intent_label or 'Informational'}",
            "Must-have competitor consensus topics should appear before differentiating gaps.",
            "Competitor body archetypes, semantic reasoning, EAV rows, and PAA should directly shape section order.",
        ]
        + _outline_logic_rules()
        + _intent_outline_policy(intent_label),
        format_lines=[
            'Return raw JSON only: [{"level":"H2","text":"...","children":[{"level":"H3","text":"..."}]}].',
            "Every H2 should be specific, evidence-grounded, and suitable for a human writer brief.",
        ],
        example_lines=[
            'Good: [{"level":"H2","text":"[MAIN] X la gi va pham vi ap dung cua X","children":[{"level":"H3","text":"X duoc phan loai theo tieu chi nao?"}]}]',
            'Bad: [{"level":"H2","text":"Tong quan"},{"level":"H2","text":"Loi ich"}]',
        ],
        guardrail_lines=[
            "Do not write article paragraphs.",
            "Do not add sections that have no support from SERP, competitor, EAV, or semantic reasoning evidence.",
            "Do not wrap the JSON in markdown code fences.",
        ],
    )
    system_prompt = _render_prompt_document(
        system_contract,
        [
            ("METHODOLOGY", methodology_prompt or "General Semantic SEO methodology."),
            (
                "OUTPUT RULES",
                "\n".join(
                    [
                        "- Keep contextual flow coherent from one H2 to the next.",
                        "- Use [MAIN] and [SUPP] only when they clarify section priority.",
                        "- Ensure at least half of the main H2 sections can support one or more H3 children.",
                        "- Use EAV attributes, semantic terms, and competitor evidence to keep H2 wording specific.",
                    ]
                ),
            ),
        ],
    )
    user_contract = _render_prompt_contract(
        role_lines=["Input package for Agent 1 outline synthesis."],
        task_lines=["Use the evidence below to produce the final H2/H3 outline JSON."],
        context_lines=[
            f"Focus keyword: {topic}",
            f"Intent label: {intent_label or 'Informational'}",
        ],
        format_lines=[
            'Return one JSON array of heading objects with "level", "text", and optional "children".',
        ],
        example_lines=[
            '[{"level":"H2","text":"...","children":[{"level":"H3","text":"..."}]}]',
        ],
    )
    user_prompt = _render_prompt_document(
        user_contract,
        [
            ("SEMANTIC CONTEXT", semantic_context),
            ("COMPETITOR AND SERP INPUTS", competitor_inputs),
        ],
    )
    return system_prompt, user_prompt


def build_agent2_semantic_prompts(
    *,
    entity: str,
    intent_label: str,
    vectors_text: str,
    headings_json: str,
    input_h2_count: int,
    input_h3_count: int,
) -> Tuple[str, str]:
    system_contract = _render_prompt_contract(
        role_lines=[
            "You are Agent 2, the Semantic SEO heading rewriter.",
            "You improve heading wording without changing the outline architecture.",
        ],
        task_lines=[
            "Rewrite H2 and H3 labels for clarity, specificity, and intent fit.",
            "Preserve section order, section count, and hierarchy.",
            "Keep headings user-facing and semantically grounded.",
        ],
        context_lines=[
            f"Central entity: {entity}",
            f"Target intent: {intent_label or 'Informational'}",
            "The outline logic is already approved; only the wording may change.",
        ]
        + _outline_logic_rules(),
        format_lines=[
            'Return raw JSON only: [{"level":"H2","text":"..."},{"level":"H3","text":"..."}].',
            f"Preserve exactly {input_h2_count} H2 items and at least {input_h3_count} H3 items.",
        ],
        example_lines=[
            'Weak: {"level":"H2","text":"Tong quan"}',
            'Strong: {"level":"H2","text":"[MAIN] X la gi va pham vi ap dung cua X"}',
        ],
        guardrail_lines=[
            "Do not add, delete, merge, or reorder headings.",
            "Do not output markdown code fences or commentary.",
            "Do not create generic labels such as overview, conclusion, or benefits without a specific semantic target.",
        ],
    )
    system_prompt = _render_prompt_document(
        system_contract,
        [
            (
                "REWRITE RULES",
                "\n".join(
                    [
                        "- Prefer question style when it improves intent fit and readability.",
                        "- Keep sibling headings harmonized in grammatical style.",
                        "- FAQ headings should stay close to real search-question phrasing.",
                        "- H3 labels must deepen the parent H2 rather than repeat it.",
                    ]
                ),
            ),
            ("CONTEXT VECTORS", vectors_text),
        ],
    )
    user_contract = _render_prompt_contract(
        role_lines=["Input package for Agent 2 heading rewrite."],
        task_lines=["Rewrite the heading payload below without changing its structure."],
        context_lines=[
            f"Central entity: {entity}",
            f"Intent label: {intent_label or 'Informational'}",
        ],
        format_lines=['Return one JSON array with keys "level" and "text".'],
        example_lines=['[{"level":"H2","text":"..."},{"level":"H3","text":"..."}]'],
    )
    user_prompt = _render_prompt_document(
        user_contract,
        [("HEADINGS TO REWRITE", headings_json)],
    )
    return system_prompt, user_prompt


def build_agent3_micro_brief_prompts(
    *,
    topic: str,
    entity: str,
    intent_label: str,
    niche: str,
    methodology_prompt: str,
    prompt_pack_text: str,
    input_package_text: str,
) -> Tuple[str, str]:
    system_contract = _render_prompt_contract(
        role_lines=[
            "You are Agent 3, the writer-brief packaging strategist.",
            "You convert a locked outline into high-value micro-brief instructions for a human writer.",
        ],
        task_lines=[
            "Keep every H2 title exactly as provided.",
            "Produce one SAPO entry plus one micro-brief object for every H2 section.",
            "For each section, provide intent, snippet, analysis, entities, information gain, bridge, and transition guidance.",
        ],
        context_lines=[
            f"Focus keyword: {topic}",
            f"Central entity: {entity}",
            f"Intent label: {intent_label or 'Informational'}",
            f"Niche: {niche}",
            "SECTION CONTEXT MAP, clean fact packs, semantic reasoning, and EAV evidence are hard context.",
        ]
        + _outline_logic_rules(),
        format_lines=[
            'Return raw JSON only: [{"h2":"SAPO ...","intent":"...","snippet":"...","analysis":"...","entities":"...","info_gain":"...","bridge":"...","transition":"..."}].',
            "Keep the output as a writer brief, not article prose.",
        ],
        example_lines=[
            'Good: {"h2":"[MAIN] X la gi","intent":"Definitional","snippet":"Tra loi truc dien trong <=40 tu ...","analysis":"Noi ro bang chung, bang so, va huong trien khai cho writer ..."}',
            'Bad: {"h2":"[MAIN] X la gi","analysis":"Bai viet nay se..." }',
        ],
        guardrail_lines=[
            "Do not rename or reorder H2 headings.",
            "Do not write the full article body.",
            "Do not output markdown code fences or explanatory prose outside JSON.",
        ],
    )
    system_prompt = _render_prompt_document(
        system_contract,
        [
            ("METHODOLOGY", methodology_prompt or "General Semantic SEO methodology."),
            (
                "SECTION RULES",
                "\n".join(
                    [
                        "- SAPO must open with a direct answer to the main query and preview the article value.",
                        "- Snippet guidance should read like content intent, not like meta commentary about writing.",
                        "- Analysis should specify evidence type, table shape, and factual requirements when relevant.",
                        "- Information gain should explicitly mention H3 coverage when the section has child headings.",
                        "- MỤC NÀY BẮT BUỘC PHẢI DÙNG ĐÚNG FORMAT NÀY: 'Các H3 trong phần này bao gồm: [Tên H3 1], [Tên H3 2].'",
                        "- DÙNG FORMAT: 'Các H3 trong phần này bao gồm: [Tên H3 1], [Tên H3 2].'",
                        "- Transition guidance must connect naturally to the next section without sounding templated.",
                    ]
                ),
            ),
            ("PROMPT PACKS", prompt_pack_text),
        ],
    )
    user_contract = _render_prompt_contract(
        role_lines=["Input package for Agent 3 micro-brief generation."],
        task_lines=["Use the locked outline and evidence below to build the final micro-brief JSON."],
        context_lines=[
            f"Focus keyword: {topic}",
            f"Central entity: {entity}",
            f"Intent label: {intent_label or 'Informational'}",
        ],
        format_lines=[
            'Return one JSON array of micro-brief objects.',
        ],
        example_lines=[
            '[{"h2":"SAPO (Doan mo dau)","intent":"Overview","snippet":"...","analysis":"...","entities":"...","info_gain":"...","bridge":"...","transition":"..."}]',
        ],
    )
    user_prompt = _render_prompt_document(
        user_contract,
        [("INPUT PACKAGE", input_package_text)],
    )
    return system_prompt, user_prompt
