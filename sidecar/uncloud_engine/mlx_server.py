"""Uncloud's bounded-thinking extension to the resident native MLX server.

Keep MLX's model loading, template, cache, batching, cancellation and streaming.
Only requests with thinking_budget_tokens receive a request-local sampler that
can emit the tokenizer's real thinking-end sequence before the answer budget.
No model imports occur when this module is imported by the sidecar or tests.
"""

from __future__ import annotations

import inspect


def compatible_source(source: str) -> bool:
    return all(marker in source for marker in (
        "def _make_sampler(args, tokenizer)", "def _tokenize(self, tokenizer, request, args)",
        "def handle_completion(self, request:", "args.chat_template_kwargs",
        "think_end_tokens", "initial_state = \"reasoning\"",
    ))


class BoundedThinkingSampler:
    """Bound aggregate reasoning across reopened blocks; preserve natural endings.

    State remains on the device. There is no per-token .item(), .tolist(), history
    scan, tokenization, CPU/GPU synchronization, or second generation request.
    Each sequential/batched request owns its own sampler and state.
    """

    def __init__(self, sampler, end_tokens, budget: int, arrays, *, start_tokens=(),
                 initial_thinking=True):
        self.sampler = sampler
        self.arrays = arrays
        self.end_tokens = arrays.array(tuple(end_tokens))
        self.end_length = len(end_tokens)
        if not self.end_length:
            raise ValueError("The tokenizer does not declare a thinking-end sequence.")
        self.budget = budget
        self.inside = arrays.array(initial_thinking)
        self.spent = arrays.array(0)
        self.forcing_index = arrays.array(0)
        self.matched = arrays.array(0)
        self.start_tokens = arrays.array(tuple(start_tokens))
        self.start_length = len(start_tokens)
        self.start_matched = arrays.array(0)

    def __call__(self, logprobs):
        mx = self.arrays
        token = self.sampler(logprobs)
        forcing = mx.logical_and(self.inside, self.spent >= self.budget)
        end = mx.take(self.end_tokens, mx.minimum(self.forcing_index, self.end_length - 1))
        token = mx.where(forcing, mx.full_like(token, end), token)
        expected = mx.take(self.end_tokens, mx.minimum(self.matched, self.end_length - 1))
        self.matched = mx.where(token == expected, self.matched + 1,
                                mx.where(token == self.end_tokens[0], 1, 0))
        closed = self.matched == self.end_length
        opened = False
        if self.start_length:
            start = mx.take(self.start_tokens,
                            mx.minimum(self.start_matched, self.start_length - 1))
            self.start_matched = mx.where(token == start, self.start_matched + 1,
                                          mx.where(token == self.start_tokens[0], 1, 0))
            opened = self.start_matched == self.start_length
        self.spent = self.spent + mx.where(
            mx.logical_and(self.inside, mx.logical_not(mx.logical_or(forcing, closed))), 1, 0)
        self.inside = mx.where(closed, False, mx.logical_or(self.inside, opened))
        self.forcing_index = mx.where(forcing, self.forcing_index + 1, 0)
        return token


def install(server, arrays) -> None:
    """Extend only this child process; never modify the installed MLX package."""
    if getattr(server, "_uncloud_bounded_thinking", False):
        return
    tokenize = server.ResponseGenerator._tokenize
    make_sampler = server._make_sampler
    complete = server.APIHandler.handle_completion
    if len(inspect.signature(make_sampler).parameters) != 2:
        raise RuntimeError("This MLX runtime is incompatible with bounded thinking.")

    def bounded_completion(self, request, stop_words):
        budget = self.body.get("thinking_budget_tokens")
        if budget is not None:
            if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
                raise ValueError("Thinking budget must be a nonnegative whole number.")
            self.chat_template_kwargs = {
                **(self.chat_template_kwargs or {}), "_uncloud_thinking_budget": budget,
            }
        return complete(self, request, stop_words)

    def bounded_tokenize(self, tokenizer, request, args):
        result = tokenize(self, tokenizer, request, args)
        args._uncloud_initial_reasoning = result[-1] == "reasoning"
        kwargs = args.chat_template_kwargs or {}
        budget = kwargs.get("_uncloud_thinking_budget")
        if budget is not None and (args._uncloud_initial_reasoning
                                  or kwargs.get("enable_thinking") is not False):
            # Native batching catches tokenization errors and returns them to
            # this request. Its sampler construction is outside that guard;
            # validate here so an unsupported request cannot kill the worker.
            if self.model_provider.draft_model is not None:
                raise ValueError("Bounded thinking is not supported with an MLX draft model.")
            ending = tokenizer.think_end_tokens
            if not tokenizer.has_thinking or not ending:
                raise ValueError("This tokenizer does not support a bounded thinking transition.")
            if budget + len(ending) >= args.max_tokens:
                raise ValueError("Thinking budget must leave room for the boundary and an answer.")
            if any(token in tokenizer.eos_token_ids for token in ending):
                raise ValueError("The model's thinking boundary also ends generation; "
                                 "it cannot reserve an answer.")
        return result

    def bounded_sampler(args, tokenizer):
        sampler = make_sampler(args, tokenizer)
        kwargs = args.chat_template_kwargs or {}
        budget = kwargs.get("_uncloud_thinking_budget")
        initial_thinking = getattr(args, "_uncloud_initial_reasoning", False)
        if budget is None or (not initial_thinking and kwargs.get("enable_thinking") is False):
            return sampler
        ending = tokenizer.think_end_tokens
        return BoundedThinkingSampler(sampler, ending, budget, arrays,
                                      start_tokens=tokenizer.think_start_tokens,
                                      initial_thinking=initial_thinking)

    server.APIHandler.handle_completion = bounded_completion
    server.ResponseGenerator._tokenize = bounded_tokenize
    server._make_sampler = bounded_sampler
    server._uncloud_bounded_thinking = True


def main() -> None:
    import mlx.core as mx
    from mlx_lm import server

    # Older/newer incompatible MLX versions keep their native server behavior.
    # Discovery does not advertise a thinking budget for those versions.
    if compatible_source(inspect.getsource(server)):
        install(server, mx)
    server.main()


if __name__ == "__main__":
    main()
