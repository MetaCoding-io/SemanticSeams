# Publishing the site

The project page and this docs site are published together as one GitHub Pages site,
by the `Deploy Pages` workflow (`.github/workflows/deploy-pages.yml`). This page explains
how that works today and how to move it to a custom domain.

## How it works today

On every push to `main` that touches `site/`, `docs/`, `ontology/` or the workflow
itself, the workflow:

1. Installs the Python dev requirements, so the reference-page generator can read the
   ontology with rdflib.
2. Runs `npm ci` and `npm run build` in `docs/`, with `DOCS_BASE=/SemanticSeams/docs/`.
   The build runs `docs/scripts/generate.py` first, then VitePress.
3. Copies `site/` to the root of one artifact and the built docs to `docs/` inside it.
4. Deploys that artifact to GitHub Pages.

| Address | Content |
|---|---|
| `https://metacoding-io.github.io/SemanticSeams/` | The project page, from `site/` |
| `https://metacoding-io.github.io/SemanticSeams/docs/` | This docs site, from `docs/` |

The repository setting this relies on is **Settings → Pages → Source → GitHub Actions**.
No `CNAME` file is needed: with an Actions deployment, the custom domain lives in the
repository's Pages settings.

The CI workflow also builds the docs on every pull request, so a broken internal link or
a change that breaks the generator fails before it can reach `main`.

## Moving to a custom domain

There are two ways to do it. Option A is one DNS record and four small edits. Option B
matches how regulator is published, with the docs on their own `docs.` subdomain, and
needs a second repository.

| | Option A: one domain | Option B: two domains |
|---|---|---|
| Addresses | `semanticseams.metacoding.io/` for the project page, `semanticseams.metacoding.io/docs/` for the docs | `semanticseams.metacoding.io/` for the project page, `docs.semanticseams.metacoding.io/` for the docs |
| Repositories | This one | This one for the docs, plus a new `semanticseams-website` for the project page |
| DNS records | One | Two |
| Matches regulator | No | Yes |

The names below are examples; use whatever subdomain you choose.

### Before either option: verify the domain

Verifying the domain for the organization stops anyone else from claiming a subdomain
of it on GitHub Pages. Verifying `metacoding.io` covers all of its subdomains, so if it
was verified when the regulator docs were set up, skip this.

1. In the **MetaCoding-io organization's** settings, open **Pages** and choose
   **Add a domain**.
2. Enter `metacoding.io`. GitHub shows a TXT record to create, named
   `_github-pages-challenge-metacoding-io.metacoding.io`, with a value it generates.
3. Create that TXT record at the DNS provider, wait for it to propagate, and choose
   **Verify**.

### Option A: one domain for both

**1. Create the DNS record.** At the DNS provider for `metacoding.io`:

```txt
semanticseams.metacoding.io.   CNAME   metacoding-io.github.io.
```

The target is the organization's Pages host, without the repository name.

**2. Set the domain on the repository.** In this repository, open **Settings → Pages**,
enter `semanticseams.metacoding.io` under **Custom domain**, and save. GitHub checks the
DNS record and then requests a certificate. Once the certificate is issued, which is
usually quick but can take a while, tick **Enforce HTTPS**.

From then on, the old `metacoding-io.github.io/SemanticSeams/` addresses redirect to the
new domain.

**3. Change the base path and the absolute links.** The site is now served from the
domain's root instead of from `/SemanticSeams/`, so the docs must be built for `/docs/`.
Make these edits in one pull request:

| File | Change |
|---|---|
| `.github/workflows/deploy-pages.yml` | `DOCS_BASE: /SemanticSeams/docs/` becomes `DOCS_BASE: /docs/` |
| `docs/.vitepress/config.ts` | The default in `const BASE` becomes `"/docs/"`, and `PROJECT_PAGE` becomes `"https://semanticseams.metacoding.io/"` |
| `site/index.html` | The `canonical`, `og:url`, `og:image` and `twitter:image` URLs move to `https://semanticseams.metacoding.io/` |
| `README.md` | The project-page and docs links move to the new domain |

The project page links to the docs with the relative path `docs/`, so that link needs
no change.

**4. Check it.** After the merge deploys, open `https://semanticseams.metacoding.io/`
and `https://semanticseams.metacoding.io/docs/`, and confirm that the padlock shows a
valid certificate and that a docs page loads its styles. A page without styles means
the base path and the address disagree.

### Option B: a docs subdomain, as regulator does

A repository has one Pages site and one custom domain, so two domains mean two
repositories: the docs stay here, and the project page moves to its own repository, the
way `regulator-website` serves `regulator.metacoding.io`.

**1. Create the DNS records.**

```txt
semanticseams.metacoding.io.        CNAME   metacoding-io.github.io.
docs.semanticseams.metacoding.io.   CNAME   metacoding-io.github.io.
```

**2. Move the project page to its own repository.**

1. Create `MetaCoding-io/semanticseams-website` and copy `site/` into it.
2. Add a Pages workflow that uploads that directory as it is. The version of
   `deploy-pages.yml` from before the docs site was added does exactly that.
3. In the new repository, set **Settings → Pages → Source** to **GitHub Actions**, set
   the custom domain to `semanticseams.metacoding.io`, and enforce HTTPS once the
   certificate is issued.
4. Change the project page's links to the docs from the relative `docs/` to
   `https://docs.semanticseams.metacoding.io/`, and update its `canonical`, `og:url`,
   `og:image` and `twitter:image` URLs.

**3. Make this repository docs-only.**

1. In `deploy-pages.yml`, build the docs with `DOCS_BASE: /`, replace the step that
   assembles `_site` so that it uploads `docs/.vitepress/dist` on its own, and drop
   `site/**` from the trigger paths.
2. In `docs/.vitepress/config.ts`, change the default in `const BASE` to `"/"` and
   `PROJECT_PAGE` to `"https://semanticseams.metacoding.io/"`.
3. Remove `site/` from this repository, and update the README's links.
4. Set this repository's custom domain to `docs.semanticseams.metacoding.io` and
   enforce HTTPS once the certificate is issued.

**4. Check both addresses** as in option A, step 4.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| The Custom domain field reports that DNS is not configured | The CNAME record has not propagated yet, or points at something other than `metacoding-io.github.io` |
| Enforce HTTPS is greyed out | The certificate has not been issued yet; it appears once the DNS check passes |
| Docs pages load without styles or return 404 | `DOCS_BASE` does not match the path the docs are served from |
| The deploy workflow fails at the docs build | The same failure shows in the CI `docs` job on the pull request; run `npm run build` in `docs/` to reproduce it |
