# Readwise Reader import threat model

Protected assets are the Readwise token, private source documents and metadata, Reader
library state, manifests, and exported files. Markdown/frontmatter, manifests, paths,
converter output, API responses, and retry headers are untrusted.

Required controls:

- Keep tokens and private document content out of logs, fixtures, errors, examples, shell
  history guidance, and source control.
- `--dry-run` must never make a mutating network request; Reader writes must preserve the
  intended URL identity and avoid updating an unrelated existing item.
- Validate manifest and output paths, avoid unsafe symlink traversal, and invoke optional
  converters without a shell.
- Bound document size, API timeouts, retry count, and `Retry-After`; redact provider errors
  before displaying them alongside private content.
- Use synthetic documents and mocked API responses in tests.

Update this model when token resolution, manifests, converters, export paths, API mutation,
retry behavior, or logging changes.
