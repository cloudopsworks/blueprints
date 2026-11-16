# Shared monorepo v1 conformance corpus

The schema and seven named canonical record examples are extracted verbatim from the approved planning contract. The identical Go/Python corpus is authoritative test data, not an independent YAML resolver.

`cases.json` separates structural/intrinsic semantic validation from linked trusted-context and actual-byte artifact validation. External GitHub receipt/account/run facts cannot be inferred from a serialized claim; context cases require supplied trusted API responses. Resolve `context.plan` / `context.manifest` fixture paths before linked validation. Descriptive expectedReason documents the rejection; consumers must reject but are not coupled to an error-message spelling.

For artifact cases validate the actual `artifact` path against `payload.mainArtifact`; the illustrative seven canonical examples intentionally use placeholder serialization digests, not real-byte proofs. OCI digest/size mean selected root descriptor bytes, NOT exported tar bytes. The two valid OCI transports have different outer hashes but the same image descriptor. Corrupt/missing/unexpected/unsafe entries must reject. ZIP and OpenAPI digest/size mean exact payload bytes.

Network/probe/GitHub/cloud correctness still needs adapter tests with trusted injected responses and later credentialed rollout; accepting these records is never authority.

OpenAPI artifact cases include digest-correct malformed and invalid documents, not
only byte-corruption negatives. Go is the sole JSON/YAML document parser: supported
Swagger 2.0/OpenAPI 3.0.x/3.1.x, required string info and object paths. Python
conformance requires a freshly built trusted Tronador on PATH (or absolute
TRONADOR_TEST_BINARY) and delegates exact original bytes to its bounded data-only
`components validate-openapi --format` command. No Python YAML dependency is used.
