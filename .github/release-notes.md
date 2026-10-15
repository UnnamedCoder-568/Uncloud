Copy, Note and Chisel now appear when you hover over an answer, keeping Chat quieter. Message spacing stays consistent: controls float beneath the answer without adding an empty action row or moving the next message. Keyboard focus reveals the same controls; touch screens keep them visible.

Fixed streamed code blocks freezing on the first incoming chunk. Display, copy and download now follow the arriving code until you explicitly edit a working copy. Explicit edits remain intact. Switching conversations also resets message-local state instead of carrying an edited block into another conversation.

Chisel's planner, tools and inference behavior are unchanged. Regression checks exercise a real workspace file write and read-back after approval, deny the write when permission is refused, and reject a code-only response as completed tool work. The model still interprets the coding request; a formatted code example is not proof that files were changed.

The Guide explains the quieter reply controls. Updated the development-only source-map dependency to address its published denial-of-service advisory. No model weights were loaded for this release's tests.

Validation: 1,090 backend tests passed with three skipped in an isolated release-source archive, plus 152 frontend and five desktop tests. Browser checks measured zero layout movement on hover and focus and verified touch access. Focused Chisel, permissions, computer-input and workflow checks passed (87 tests). The browser check used the app's actual CSS in an isolated fixture, not the user's Chrome session. Full validation details are in [the Chat UI report](https://github.com/UnnamedCoder-568/Uncloud/blob/main/qa/chat-actions-review-2026-10-15.md).
