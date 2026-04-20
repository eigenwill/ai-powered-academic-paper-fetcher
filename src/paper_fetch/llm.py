"""Optional LLM query rewriter (litellm-backed).

This is kept off the critical path — `--smart` opts in. For well-formed
natural queries Semantic Scholar's relevance ranking already does a good
job. The LLM earns its keep on ambiguous, domain-heavy queries ("silicon
phototransistor mechanism") where keyword boosting helps.

Structured output is preferred (JSON schema) to avoid parsing free-form text.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You rewrite natural-language academic search queries into keyword form for the Semantic Scholar API.

Return ONLY a valid JSON object with this shape:
{
  "keywords": ["string", ...],        # 3-8 terms, lowercase where possible
  "boolean_query": "string",           # combine keywords with AND/OR
  "year_min": <integer or null>        # only if the user explicitly requested recent work
}

Do not include prose, explanations, or markdown. Return JSON only."""


@dataclass
class SearchQuery:
    keywords: list[str]
    boolean_query: str
    year_min: int | None


def _parse_json_loose(s: str) -> dict:
    """Extract the first JSON object from a string — handles code fences."""
    s = s.strip()
    # Strip ```json fences if the model added them anyway
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    # Find the outermost {...}
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in LLM response: {s!r}")
    return json.loads(m.group(0))


def rewrite_query(nl_query: str, *, model: str, api_key: str | None = None) -> SearchQuery:
    """Rewrite a natural-language query to keyword form.

    Any failure (model unreachable, malformed JSON) returns a SearchQuery
    that just echoes the original query — the caller should never crash
    because the LLM is flaky.
    """
    fallback = SearchQuery(keywords=[nl_query], boolean_query=nl_query, year_min=None)
    try:
        # Imported lazily so users who never pass --smart don't pay for litellm init.
        import litellm  # type: ignore
    except Exception as e:
        logger.warning("litellm not available: %s", e)
        return fallback

    try:
        resp = litellm.completion(
            model=model,
            api_key=api_key,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": nl_query},
            ],
            temperature=0,
            # response_format is honored by providers that support it; others ignore it.
            response_format={"type": "json_object"},
        )
        content = resp["choices"][0]["message"]["content"]
        parsed = _parse_json_loose(content)
        return SearchQuery(
            keywords=list(parsed.get("keywords") or []),
            boolean_query=str(parsed.get("boolean_query") or nl_query),
            year_min=parsed.get("year_min"),
        )
    except Exception as e:
        logger.warning("LLM rewrite failed, falling back to raw query: %s", e)
        return fallback
