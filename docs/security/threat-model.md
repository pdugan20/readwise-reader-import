# Readwise Reader import threat model

Protected assets are the Readwise token, private source documents and metadata, Reader
library state, manifests, and exported files. Markdown/frontmatter, manifests, paths,
converter output, API responses, and retry headers are untrusted.

Source boundaries: `readwise_reader_import/importer.py` collects local documents, invokes
converters with argument arrays, and sends authenticated Reader requests. The following
are required review controls, not a claim that every current path implements them.

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

## Enforced import boundaries

`_send()` uses a 30-second socket-operation timeout and at most 1 MiB of response bytes.
Only HTTP 429 retries, at most four attempts, with each Retry-After delta/date capped at
60 seconds and malformed headers falling back to bounded backoff. Redirects are rejected
and provider error bodies/protocol details are not printed. Success response shape/status
and update identity are checked before reporting success. These bounds are not a whole-job deadline.

Manifest and directory-discovered inputs are checked against the resolved job root before
any API import. Relative nested files and contained symlink aliases retain their identity;
absolute paths and source/parent-directory escapes are rejected, while missing files keep the existing skip
behavior. A directly selected file is an explicit operator-selected input. The operator
must control the job directory throughout the run: this is not isolation from concurrent
filesystem changes by another local process. Optional converters remain trusted local
tools invoked with argument arrays; source volume and conversion work remain operator
responsibilities.

Dry runs neither send Reader writes nor save adjacent HTML. Normal HTML writes are staged
in the destination directory and atomically replace the output without following its
symlink. Failures preserve previous output and remove the temporary file.
