"""Objective same-model transport and real compaction evaluation; no user data."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

from benchmark_chat import measure
from uncloud_engine import chat_transport, inference_profile
from uncloud_engine.context_count import _count_mlx

CASES = [
    (
        "multi_step",
        'A shop buys 48 notebooks at 3 credits each. It sells 36 at 5 credits each and the rest at 2 credits each. What is its total profit? Return JSON only: {"profit":number}.',
        {"profit": 60},
    ),
    (
        "logic",
        'Exactly one of A, B, C is true. A says B is false. B says C is false. C says A and B are both false. Which statement is true? Return JSON only: {"true":"A or B or C"}.',
        {"true": "B"},
    ),
    (
        "constraints",
        "Schedule three tasks. Test must follow Build. Ship must follow Test. Return only a JSON array of the three task names in order, with exact capitalization.",
        ["Build", "Test", "Ship"],
    ),
    (
        "code_reasoning",
        "What does this Python code print?\na=[1,2]\nb=a\na=a+[3]\nb.append(4)\nprint(a,b)\nReturn JSON only with keys a and b and their final arrays.",
        {"a": [1, 2, 3], "b": [1, 2, 4]},
    ),
    (
        "correction",
        'The project budget was 90. Later it changed to 63. An old memo still says 90. The release date is unknown. Report the current budget and release date using JSON only. Use null for unknown: {"budget":number,"release":value}.',
        {"budget": 63, "release": None},
    ),
    (
        "unanswerable",
        'Evidence: Mira owns a blue bicycle. No other facts are available. What is Mira\'s age? Reply with JSON only: {"age":null} if unsupported. Do not infer from bicycle ownership.',
        {"age": None},
    ),
]


def parse(answer):
    try:
        return json.loads(answer.strip())
    except ValueError:
        return None


def factual_grade(answer, expected):
    """Separate strict JSON compliance from facts, allowing only cosmetic differences."""
    clean = answer.strip()
    if clean.startswith("```json") and clean.endswith("```"):
        clean = clean[7:-3].strip()
    actual = parse(clean)

    def normalize(value, key=""):
        if isinstance(value, str):
            value = value.strip().rstrip(".").casefold()
            if key == "reference" and value.startswith("issue "):
                value = value[6:]
        elif isinstance(value, list):
            value = [normalize(item, key) for item in value]
        return value

    if isinstance(expected, dict):
        checks = {
            key: isinstance(actual, dict)
            and normalize(actual.get(key), key) == normalize(value, key)
            for key, value in expected.items()
        }
        return {"passed": all(checks.values()), "fields": checks}
    return {"passed": normalize(actual) == normalize(expected)}


def memory_prompt(history, previous=""):
    turns = "\n\n".join(m["role"].upper() + ": " + m["content"] for m in history)
    source = (
        Path(__file__).resolve().parents[1] / "uncloud/src/lib/context.ts"
    ).read_text()
    instructions = re.search(r"COMPACTION_INSTRUCTION = `([^`]+)`", source).group(1)
    instruction = (
        instructions
        + "\n\nExisting compacted memory (update it without losing facts):\n"
        + (previous or "(none)")
        + "\n\nNew conversation turns:\n"
        + turns
    )
    return [
        {
            "role": "system",
            "content": "You maintain accurate, concise conversation memory.",
        },
        {"role": "user", "content": instruction},
    ]


def fixture():
    facts = [
        "Our project is called Juniper. Build an offline catalogue for a library. The workspace is /projects/juniper. The owner is Nila.",
        "We first considered a 90 credit budget and a Friday release. Do not send any data to cloud services. Use SQLite and keep exports as CSV.",
        "Decision: the budget is now 63 credits, replacing 90. Release moves to Tuesday, replacing Friday. Preserve existing books during migration.",
        "Unresolved tasks: test accented author names and get Nila to approve the migration. The reference is issue LIB-42. Never delete the original catalogue.",
    ]
    history = []
    for index, fact in enumerate(facts):
        history += [
            {"role": "user", "content": fact},
            {
                "role": "assistant",
                "content": "Recorded. I will follow these project decisions.",
            },
        ]
        for j in range(6):
            history += [
                {
                    "role": "user",
                    "content": f"Historical review note {index}-{j}: We reviewed shelf labels, paper textures, desk placement, and lighting. This was only an exploratory discussion; none of those observations changes the software requirements or project decisions.",
                },
                {
                    "role": "assistant",
                    "content": "Those exploratory observations are noted. The established project requirements remain in effect. We can revisit visual details after the catalogue and migration are verified.",
                },
            ]
    return history


async def run(args):
    profile, defaults = inference_profile.load(args.model_path, "mlx")
    active = SimpleNamespace(
        base_url=args.base_url,
        engine="mlx",
        model_profile=profile,
        inference_profile=defaults,
    )
    root = Path(args.model_path).parent
    report = {
        "model": Path(args.model_path).name,
        "sampling": {"temperature": 0, "seed": 42},
        "records": [],
        "compaction": [],
        "limitations": [
            "One MLX model; reconstructed legacy transport, not historical binary",
            "Synthetic controlled context, not a full native-window stress test",
            "Deterministic evaluation overrides sampling; production retains native/user settings",
        ],
    }

    def save():
        Path(args.output).write_text(json.dumps(report, indent=2))

    async def check(label, messages, expected):
        for mode in ("direct", "legacy", "optimized"):
            result = await measure(mode, active, messages, root, args.max_tokens)
            result.update(
                case=label,
                expected=json.loads(json.dumps(expected)),
                passed=parse(result["answer"]) == expected,
                factual=factual_grade(result["answer"], expected),
            )
            report["records"].append(result)
            save()
            print(
                json.dumps(
                    {k: result[k] for k in ("case", "mode", "passed", "ttft_ms")}
                ),
                flush=True,
            )

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
        report["prior_budget_results"] = baseline["records"]
        report["prior_compaction"] = baseline["compaction"]
    for name, prompt, expected in CASES:
        if args.baseline and name != "logic":
            report["records"].extend(
                r for r in baseline["records"] if r["case"] == name
            )
            continue
        await check(name, [{"role": "user", "content": prompt}], expected)
    history = fixture()
    expected = {
        "project": "Juniper",
        "owner": "Nila",
        "budget": 63,
        "release": "Tuesday",
        "database": "SQLite",
        "export": "CSV",
        "workspace": "/projects/juniper",
        "reference": "LIB-42",
        "cloud_allowed": False,
        "delete_original": False,
        "pending": ["test accented author names", "get Nila to approve the migration"],
    }
    question = {
        "role": "user",
        "content": "Using only our project decisions, return JSON only with these keys: project, owner, budget, release, database, export, workspace, reference, cloud_allowed (boolean), delete_original (boolean), pending (array of the two unresolved tasks in their stated order, using the original wording).",
    }
    await check("full_context", history + [question], expected)
    # Retain recent turns exactly as the UI does; summarize only the older prefix.
    prefix, tail = history[:-2], history[-2:]
    result = await measure(
        "optimized", active, memory_prompt(prefix), root, args.max_tokens
    )
    summary = result["answer"].strip()
    compacted = [
        {
            "role": "system",
            "content": "Earlier conversation, compacted for continuity:\n" + summary,
        },
        *tail,
    ]
    before = _count_mlx(args.model_path, history + [question])
    after = _count_mlx(args.model_path, compacted + [question])
    report["compaction"].append(
        {
            "round": 1,
            "before_tokens": before,
            "after_tokens": after,
            "reduced": after < before,
            "summary": summary,
        }
    )
    save()
    await check("compacted_context", compacted + [question], expected)
    updates = [
        {
            "role": "user",
            "content": "Update: Nila approved the migration. Only testing accented author names remains unresolved. Budget is unchanged. Release moves to Wednesday. Preserve all other decisions.",
        },
        {"role": "assistant", "content": "Recorded the approval and new release day."},
    ]
    result = await measure(
        "optimized",
        active,
        memory_prompt(tail + updates, summary),
        root,
        args.max_tokens,
    )
    second = result["answer"].strip()
    report["compaction"].append(
        {
            "round": 2,
            "summary": second,
            "input_contains_only_previous_summary_and_new_turns": True,
        }
    )
    save()
    expected = {
        **expected,
        "release": "Wednesday",
        "pending": ["test accented author names"],
    }
    question2 = {
        **question,
        "content": question["content"].replace(
            "the two unresolved tasks", "the remaining unresolved tasks"
        ),
    }
    await check(
        "incremental_compaction",
        [
            {
                "role": "system",
                "content": "Earlier conversation, compacted for continuity:\n" + second,
            },
            question2,
        ],
        expected,
    )
    await chat_transport.close()
    save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18473")
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--max-tokens", type=int, default=3072)
    asyncio.run(run(parser.parse_args()))
