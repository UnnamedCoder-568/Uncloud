"""Native MLX server with the selected runtime's context boundary.

Model loading, templates, tokenization, sampling, reasoning, cache and streaming
belong to MLX. This adapter uses the prompt MLX already tokenized to stop input
overflow and bound output by the remaining context. It never changes tokens.
"""

from __future__ import annotations


def install_context_limit(server, limit: int) -> None:
    tokenize = server.ResponseGenerator._tokenize

    def tokenize_with_context(self, tokenizer, request, args):
        result = tokenize(self, tokenizer, request, args)
        available = limit - len(result[0])
        if available <= 0:
            raise ValueError("The conversation fills this model's runtime context. "
                             "Compact it or select a larger context window.")
        # max_tokens is a ceiling. A manual limit is never raised or persisted
        # as a different preference; only the actual remaining window bounds it.
        args.max_tokens = min(args.max_tokens, available)
        return result

    server.ResponseGenerator._tokenize = tokenize_with_context


def main() -> None:
    import os

    from mlx_lm import server

    limit = os.environ.get("UNCLOUD_CONTEXT_LIMIT")
    if limit is not None:
        install_context_limit(server, int(limit))
    server.main()


if __name__ == "__main__":
    main()
