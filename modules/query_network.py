# -*- coding: utf-8 -*-
"""
Semantic query network expansion and clustering.
"""

import json
import logging
import random
import time
from typing import Any, Dict, List

import requests

from config import LLM_CONFIG
from modules.outline_content_prompt_catalog import build_query_cluster_prompts

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


logger = logging.getLogger(__name__)

GOOGLE_AUTOCOMPLETE_URL = "http://suggestqueries.google.com/complete/search"

QUERY_TEMPLATES = [
    "{entity}",
    "{entity} là gì",
    "có nên mua {entity}",
    "{entity} cho",
    "{entity} ở",
    "{entity} tại",
    "{entity} với",
    "{entity} loại",
    "giá {entity}",
    "mua {entity}",
    "cách chọn {entity}",
]


def _normalize_cluster_item(cluster: Any, fallback_idx: int = 0) -> Dict:
    """Normalize one cluster into the schema used by downstream modules."""
    if not isinstance(cluster, dict):
        return {}

    cluster_name = str(
        cluster.get("cluster_name")
        or cluster.get("name")
        or f"Cluster {fallback_idx}"
    ).strip()
    intent = str(cluster.get("intent") or "N/A").strip()
    primary_keyword = str(
        cluster.get("primary_keyword")
        or cluster.get("main_keyword")
        or cluster.get("keyword")
        or ""
    ).strip()

    variants_raw = cluster.get("variants")
    if variants_raw is None:
        variants_raw = cluster.get("keywords", [])

    if isinstance(variants_raw, str):
        variants = [variants_raw.strip()] if variants_raw.strip() else []
    elif isinstance(variants_raw, (list, tuple, set)):
        variants = [str(v).strip() for v in variants_raw if str(v).strip()]
    else:
        variants = []

    keywords = []
    if primary_keyword:
        keywords.append(primary_keyword)
    for kw in variants:
        if kw not in keywords:
            keywords.append(kw)
    if not primary_keyword and keywords:
        primary_keyword = keywords[0]

    normalized = dict(cluster)
    normalized["cluster_name"] = cluster_name
    normalized["name"] = cluster.get("name") or cluster_name
    normalized["intent"] = intent
    normalized["primary_keyword"] = primary_keyword
    normalized["variants"] = variants
    normalized["keywords"] = keywords
    return normalized


def normalize_cluster_payload(payload: Any) -> Dict:
    """Normalize LLM output into {'clusters': [...]} and preserve error states."""
    if payload is None:
        return {"error": "Empty clustering response", "clusters": []}

    if isinstance(payload, dict) and payload.get("error"):
        return {"error": str(payload.get("error")), "clusters": []}

    if isinstance(payload, dict):
        raw_clusters = payload.get("clusters", payload)
    elif isinstance(payload, list):
        raw_clusters = payload
    else:
        return {
            "error": f"Invalid clustering payload type: {type(payload).__name__}",
            "clusters": [],
        }

    if isinstance(raw_clusters, dict):
        raw_clusters = raw_clusters.get("clusters", [])
    if not isinstance(raw_clusters, list):
        raw_clusters = []

    normalized_clusters = []
    for idx, cluster in enumerate(raw_clusters, start=1):
        normalized = _normalize_cluster_item(cluster, fallback_idx=idx)
        if normalized:
            normalized_clusters.append(normalized)

    return {"clusters": normalized_clusters}


def _heuristic_cluster_keywords(keywords: List[str], entity: str, project=None) -> Dict:
    """Fallback clusterer when LLM is unavailable or returns empty output."""
    if not keywords:
        base = str(entity or "topic").strip()
        industry = ""
        main_products = ""
        target_customers = ""
        if project is not None:
            industry = str(getattr(project, "industry", "") or "").strip()
            main_products = str(getattr(project, "main_products", "") or "").strip()
            target_customers = str(getattr(project, "target_customers", "") or "").strip()

        seed_keywords = [base]
        if base:
            seed_keywords.extend([
                f"{base} la gi",
                f"{base} nhu the nao",
                f"chi phi {base}",
                f"rui ro {base}",
                f"cach ap dung {base}",
            ])
        if industry:
            seed_keywords.extend([
                f"{industry} {base}",
                f"{base} trong {industry}",
            ])
        if main_products:
            seed_keywords.append(f"{base} va {main_products}")
        if target_customers:
            seed_keywords.append(f"{base} cho {target_customers}")

        keywords = [kw for kw in seed_keywords if kw]

    buckets = {
        "Definition": {
            "intent": "Informational",
            "keywords": [],
            "signals": ["la gi", "dinh nghia", "khai niem", "what is"],
        },
        "How to": {
            "intent": "Informational",
            "keywords": [],
            "signals": ["cach", "nhu the nao", "quy trinh", "huong dan", "lam sao"],
        },
        "Comparison": {
            "intent": "Commercial",
            "keywords": [],
            "signals": ["so sanh", "khac nhau", "vs", "khac gi", "nang hon"],
        },
        "Price / Cost": {
            "intent": "Commercial",
            "keywords": [],
            "signals": ["gia", "phi", "chi phi", "bang gia", "bao nhieu"],
        },
        "Risk / Evaluation": {
            "intent": "Informational",
            "keywords": [],
            "signals": ["rui ro", "luu y", "uu nhuoc", "loi ich", "danh gia"],
        },
        "Navigational": {
            "intent": "Navigational",
            "keywords": [],
            "signals": ["o dau", "lien he", "dang ky", "website", "app"],
        },
        "General": {
            "intent": "Informational",
            "keywords": [],
            "signals": [],
        },
    }

    def _score_bucket(keyword: str, signals: List[str]) -> int:
        lowered = keyword.lower()
        score = 0
        for sig in signals:
            if sig in lowered:
                score += 2
        if entity and entity.lower() in lowered:
            score += 1
        return score

    for kw in keywords:
        best_name = "General"
        best_score = -1
        for bucket_name, bucket in buckets.items():
            score = _score_bucket(kw, bucket["signals"])
            if score > best_score:
                best_name = bucket_name
                best_score = score
        buckets[best_name]["keywords"].append(kw)

    clusters = []
    for bucket_name, bucket in buckets.items():
        if not bucket["keywords"]:
            continue
        primary = bucket["keywords"][0]
        clusters.append(
            {
                "cluster_name": bucket_name,
                "intent": bucket["intent"],
                "primary_keyword": primary,
                "variants": bucket["keywords"][:8],
                "keywords": bucket["keywords"][:8],
            }
        )

    if not clusters:
        base = str(entity or keywords[0]).strip()
        clusters = [
            {
                "cluster_name": "General",
                "intent": "Informational",
                "primary_keyword": base,
                "variants": [base],
                "keywords": [base],
            }
        ]

    return {"clusters": clusters}


def get_network_clusters(network_data: Any) -> List[Dict]:
    """Extract a normalized list of cluster dicts from network_data."""
    if not isinstance(network_data, dict):
        return []
    payload = normalize_cluster_payload(network_data.get("clusters"))
    return payload.get("clusters", [])


def analyze_query_network(entity: str, project=None) -> Dict:
    """
    Expand a central entity with autocomplete keywords and cluster them with an LLM.
    """
    logger.info("  [NETWORK] Bat dau phan tich Query Network cho: '%s'", entity)

    templates = _generate_query_templates(entity)
    logger.info("  [NETWORK] Da tao %d query templates", len(templates))

    all_keywords = set()
    for raw_query in templates:
        kws = _fetch_autocomplete_keywords(raw_query)
        all_keywords.update(kws)
        time.sleep(0.2)

    all_keywords_list = sorted(all_keywords)
    logger.info("  [NETWORK] Da thu thap %d tu khoa lien quan (unique)", len(all_keywords_list))

    max_kws_for_llm = 80
    if len(all_keywords_list) > max_kws_for_llm:
        prioritized = [k for k in all_keywords_list if entity.lower() in k.lower()]
        others = [k for k in all_keywords_list if k not in prioritized]

        if len(prioritized) > max_kws_for_llm:
            chosen_keywords = random.sample(prioritized, max_kws_for_llm)
        else:
            needed = max_kws_for_llm - len(prioritized)
            sampled_others = random.sample(others, needed) if len(others) >= needed else others
            chosen_keywords = prioritized + sampled_others
    else:
        chosen_keywords = all_keywords_list

    if not chosen_keywords:
        logger.warning("  [NETWORK] Khong thu thap duoc keyword nao cho '%s'", entity)
        clusters = normalize_cluster_payload(_heuristic_cluster_keywords([entity], entity, project=project))
        return {
            "raw_keywords": all_keywords_list or [entity],
            "total_fetched": len(all_keywords_list),
            "clustered_kws_count": 1,
            "clusters": clusters,
        }

    clusters = normalize_cluster_payload(_cluster_keywords_with_llm(chosen_keywords, entity))
    if clusters.get("error") or not clusters.get("clusters"):
        logger.warning("  [NETWORK] LLM clustering empty; using heuristic fallback.")
        clusters = normalize_cluster_payload(_heuristic_cluster_keywords(chosen_keywords, entity, project=project))

    result = {
        "raw_keywords": all_keywords_list,
        "total_fetched": len(all_keywords_list),
        "clustered_kws_count": len(chosen_keywords),
        "clusters": clusters,
    }

    num_clusters = len(clusters.get("clusters", [])) if "error" not in clusters else 0
    logger.info("  [NETWORK] Hoan tat clustering: %d cum", num_clusters)
    return result


def _generate_query_templates(entity: str) -> List[str]:
    return [tmpl.format(entity=entity) for tmpl in QUERY_TEMPLATES]


def _fetch_autocomplete_keywords(query: str) -> List[str]:
    params = {
        "client": "chrome",
        "hl": "vi",
        "q": query,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            GOOGLE_AUTOCOMPLETE_URL,
            params=params,
            headers=headers,
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json()
            if len(data) > 1 and isinstance(data[1], list):
                kws = [kw.lower().strip() for kw in data[1]]
                return [k for k in kws if len(k) > 3]
    except Exception as exc:
        logger.debug("  [NETWORK] Error fetching autocomplete for '%s': %s", query, exc)

    return []


def _cluster_keywords_with_llm(keywords: List[str], entity: str) -> Dict:
    if not OpenAI:
        logger.warning("  [NETWORK] Thieu thu vien 'openai'. Bo qua LLM clustering.")
        return {"error": "Missing openai library"}

    api_key = LLM_CONFIG.get("api_key")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.warning("  [NETWORK] OPENAI_API_KEY chua duoc cau hinh. Bo qua LLM clustering.")
        return {"error": "Missing OpenAI API Key"}

    client = OpenAI(
        api_key=api_key,
        base_url=LLM_CONFIG.get("base_url") if LLM_CONFIG.get("base_url") else None,
    )

    system_prompt, user_prompt = build_query_cluster_prompts(entity=entity, keywords=keywords)

    try:
        logger.info(
            "  [NETWORK] Dang gui %d keywords toi LLM (%s)...",
            len(keywords),
            LLM_CONFIG.get("model"),
        )
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=60,
        )

        content = response.choices[0].message.content
        if not content:
            logger.warning("  [NETWORK] Empty content from LLM response")
            return {"error": "Empty LLM response"}

        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("  [NETWORK] JSON parse failed: %s", exc)
            return {"error": f"JSON parse failed: {exc}"}

    except Exception as exc:
        logger.error("  [NETWORK] LLM Clustering error: %s", exc)
        return {"error": f"LLM Error: {exc}"}
