# Fulltext validation fixtures

These deliberately small, synthetic files are safe to commit and are used by
the Fulltext MCP implementation tests. `main-article.pdf` is a one-page PDF
container; provider/validator tests will add synthetic metadata for main
article, supplement, identifier-mismatch, and scanned/no-identity cases rather
than storing real paper content in the repository.

`login-page.html` guards against treating an authentication response as a PDF.
