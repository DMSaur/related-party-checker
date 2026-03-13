#!/usr/bin/env python3
"""
Related Party Transaction Checker - Optimized Version
Checks if Vietnam-China company pairs have related party relationships
Enhanced with parallel searches and reduced latency
"""

import argparse
import json
import os
import re
import time
import signal
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import pandas as pd
from ddgs import DDGS
from tqdm import tqdm

# Evidence filter keywords
EN_KEYWORDS = [
    "shareholder", "owner", "parent", "subsidiary", "affiliate", "investor",
    "related party", "joint venture", "wholly owned", "controlled by",
    "beneficial owner", "ultimate owner", "holding company", "FDI"
]
ZH_KEYWORDS = [
    "股东", "母公司", "子公司", "实际控制人", "关联方", "控股",
    "法人", "出资人", "外商投资", "全资", "参股"
]
VI_KEYWORDS = [
    "cổ đông", "công ty mẹ", "công ty con", "sở hữu", "đầu tư nước ngoài"
]
ALL_KEYWORDS = EN_KEYWORDS + ZH_KEYWORDS + VI_KEYWORDS

# Reduced search templates (5 most effective searches)
SEARCH_TEMPLATES = [
    '"{vietnam_company}" "{china_company}"',  # Direct co-occurrence
    '"{vietnam_company}" "{china_company}" subsidiary parent owner',
    '"{china_company}" shareholder 股东 母公司',
    '"{vietnam_company}" shareholder owner Vietnam FDI',
    '"{vietnam_company}" China investment foreign direct',
]

SYSTEM_PROMPT = """你是一名专业的关联交易审查员。根据搜索证据判断两家公司是否存在关联关系。
基于证据合理推断，如果公司名称高度相关且有投资/控制迹象，可判定为关联。"""

USER_PROMPT_TEMPLATE = """【证据】{evidence}

【判断】
越南公司: {vietnam_company}
中国公司: {china_company}

关联条件: 股权持有≥25%、共同实控人、高管重叠、相同地址联系方式、FDI关系、品牌相同且有投资关系。

输出JSON:
{{"conclusion":"关联/不关联/无法判断","relation_type":"母子公司/同一实控人/FDI投资关系/其他/null","confidence":"高/中/低","evidence_quote":"证据原句/null"}}"""


class RelatedPartyChecker:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url="https://coding.dashscope.aliyuncs.com/apps/anthropic",
        )
        self.model = "glm-5"

    def single_search(self, query: str, max_results: int = 5) -> list[dict]:
        """Single search with retry."""
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception:
            return []

    def parallel_search(self, queries: list[str], max_results: int = 5) -> tuple[list[dict], set]:
        """Execute searches in parallel."""
        all_results = []
        all_urls = set()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self.single_search, q, max_results): q for q in queries}

            for future in as_completed(futures):
                try:
                    results = future.result()
                    all_results.extend(results)
                    for r in results:
                        if href := r.get("href"):
                            all_urls.add(href)
                except Exception:
                    pass

        return all_results, all_urls

    def extract_evidence(self, results: list[dict]) -> str:
        """Extract and filter evidence."""
        evidence_parts = []
        for r in results:
            text = f"{r.get('title', '')} {r.get('body', '')}"
            sentences = re.split(r'[。.!?\n]', text)
            for sentence in sentences:
                sentence = sentence.strip()
                if any(kw.lower() in sentence.lower() for kw in ALL_KEYWORDS):
                    evidence_parts.append(sentence)
        evidence = " | ".join(dict.fromkeys(evidence_parts))
        return evidence[:2000] if len(evidence) > 2000 else evidence

    def judge_relationship(self, vietnam_company: str, china_company: str, evidence: str, max_retries: int = 3) -> dict:
        """Call API with retry."""
        user_prompt = USER_PROMPT_TEMPLATE.format(
            evidence=evidence,
            vietnam_company=vietnam_company,
            china_company=china_company,
        )

        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                content = ""
                for block in response.content:
                    if hasattr(block, 'text'):
                        content += block.text
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    result = json.loads(json_match.group())
                    result["error"] = None
                    return result
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))
                else:
                    return {"conclusion": "处理失败", "relation_type": None, "confidence": None,
                            "evidence_quote": None, "error": str(e)}
        return {"conclusion": "处理失败", "relation_type": None, "confidence": None,
                "evidence_quote": None, "error": "Max retries"}

    def process_pair(self, vietnam_company: str, china_company: str) -> dict:
        """Process a single pair."""
        queries = [t.format(vietnam_company=vietnam_company, china_company=china_company)
                   for t in SEARCH_TEMPLATES]

        results, urls = self.parallel_search(queries)
        evidence = self.extract_evidence(results)
        result = self.judge_relationship(vietnam_company, china_company, evidence)
        result["search_urls"] = "\n".join(sorted(urls)[:20])  # Limit URLs

        return result


class GracefulExit:
    def __init__(self):
        self.shutdown = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print(f"\n\nReceived signal, saving progress...")
        self.shutdown = True

    def should_exit(self):
        return self.shutdown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="output.xlsx")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    df_input = pd.read_csv(args.input, encoding='utf-8-sig')
    if 'importer' in df_input.columns and 'exporter' in df_input.columns:
        df_input = df_input.rename(columns={'importer': 'vietnam_company', 'exporter': 'china_company'})

    df_input = df_input.drop_duplicates(subset=['vietnam_company', 'china_company'])
    print(f"Total unique pairs: {len(df_input)}")

    if args.limit > 0:
        df_input = df_input.head(args.limit)
        print(f"Limited to {args.limit} pairs")

    output_cols = ["vietnam_company", "china_company", "conclusion", "relation_type",
                   "confidence", "evidence_quote", "search_urls", "error"]

    if Path(args.output).exists():
        df_output = pd.read_excel(args.output)
        processed = set(zip(df_output["vietnam_company"], df_output["china_company"]))
        print(f"Resuming from {len(df_output)} existing rows")
    else:
        df_output = pd.DataFrame(columns=output_cols)
        processed = set()

    checker = RelatedPartyChecker(api_key)
    graceful = GracefulExit()

    pairs = [(r["vietnam_company"], r["china_company"])
             for _, r in df_input.iterrows()
             if (r["vietnam_company"], r["china_company"]) not in processed]

    print(f"Processing {len(pairs)} pairs...")

    stats = {"R": 0, "N": 0, "U": 0, "F": 0}

    for vietnam, china in tqdm(pairs, desc="Processing"):
        if graceful.should_exit():
            break

        result = checker.process_pair(vietnam, china)

        # Stats
        c = result.get("conclusion", "")
        if c == "关联": stats["R"] += 1
        elif c == "不关联": stats["N"] += 1
        elif c == "无法判断": stats["U"] += 1
        else: stats["F"] += 1

        # Save
        row = {"vietnam_company": vietnam, "china_company": china, **result}
        df_output = pd.concat([df_output, pd.DataFrame([row])], ignore_index=True)
        df_output.to_excel(args.output, index=False)

        time.sleep(0.5)  # Rate limit

    print(f"\n完成! 关联:{stats['R']} 不关联:{stats['N']} 无法判断:{stats['U']} 失败:{stats['F']}")
    print(f"结果: {args.output}")


if __name__ == "__main__":
    main()