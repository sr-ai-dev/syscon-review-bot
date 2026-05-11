LANGUAGE_HINTS: dict[str, str] = {
    "Python": "PEP 8, type hints, context manager, list/dict comprehension, dataclass, no mutable default args",
    "TypeScript": "strict mode, type narrowing, no any, discriminated union, readonly",
    "JavaScript": "const/let over var, async/await, no implicit globals, strict equality",
    "Java": "generics, Optional, immutability (final/Record), try-with-resources, nullable annotations",
    "Kotlin": "data class, sealed class, null safety operators, immutable val, scope functions",
    "C++": "RAII, const correctness, smart pointers (unique_ptr/shared_ptr), no raw new/delete, move semantics",
    "C": "memory ownership clarity, bounds checking, no UB (UAF, double free), error return discipline",
    "C/C++ Header": "include guards, forward declarations, minimize includes",
    "C#": "var with care, async/await + ConfigureAwait, IDisposable/using, nullable reference types",
    "Go": "error returns explicitly handled, no panic in libraries, defer for cleanup, small interfaces",
    "Rust": "ownership/borrow rules, ? for error propagation, no unwrap in library, lifetime correctness",
    "Ruby": "duck typing with care, frozen strings, blocks for resource cleanup",
    "PHP": "strict types, prepared statements, input validation, no eval",
    "Swift": "optionals, value types, guard let, immutability (let)",
    "Scala": "immutability, pattern matching, Option/Either, avoid null",
    "Shell": "set -euo pipefail, quote variables, shellcheck-clean",
    "SQL": "parameterized queries, indexes for WHERE columns, no SELECT *, explicit JOIN",
    "YAML": "no tab indent, consistent quoting, anchor/alias for reuse",
    "JSON": "schema/spec adherence, no trailing comma",
    "TOML": "spec adherence",
    "XML": "schema validation, namespaces correct",
    "HTML": "semantic tags, accessibility (alt/aria), no inline JS for security",
    "CSS": "scoped selectors, no !important abuse, responsive units",
}


def build_language_section(languages: list[str]) -> str:
    if not languages:
        return ""

    lines = ["## 이번 PR의 언어 컨텍스트"]
    lines.append(f"변경된 파일의 언어: {', '.join(languages)}")
    lines.append("")
    lines.append("각 언어의 idiomatic best practice 관점에서 리뷰하라:")
    for lang in languages:
        hint = LANGUAGE_HINTS.get(lang)
        if hint:
            lines.append(f"- {lang}: {hint}")
    return "\n".join(lines)
