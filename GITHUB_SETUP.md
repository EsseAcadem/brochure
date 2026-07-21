# DT&I brochure: automatic provider catalogue

This package replaces the hard-coded paid provider courses with a small JSON catalogue that GitHub refreshes automatically.

## Included files

- `brochure_online_file.html` — updated brochure. Internal/free IT courses, soft skills and apprenticeships remain embedded.
- `data/knowledge-academy-courses.json` — cached provider catalogue used by the page.
- `scripts/update_courses.py` — catalogue scraper and validator.
- `scripts/requirements.txt` — Python dependencies.
- `.github/workflows/refresh-course-catalogue.yml` — weekly GitHub Actions schedule and manual refresh button.

The seed catalogue contains **430 courses**. The first successful workflow run replaces it with the current catalogue discovered from the provider's public category pages and XML sitemaps.

## Upload to the repository

1. Back up the existing brochure HTML.
2. Copy all files and folders from this package into the repository, preserving their paths.
3. Replace the existing brochure file with `brochure_online_file.html`, or rename this file to the page name already used by the site.
4. Keep the `data` folder beside the brochure page. The page loads `./data/knowledge-academy-courses.json`.
5. Commit and push the changes.

## Allow the workflow to update JSON

In GitHub:

1. Open **Settings → Actions → General**.
2. Under **Workflow permissions**, choose **Read and write permissions**.
3. Save the setting.

The workflow itself requests only `contents: write`, which it needs to commit the refreshed JSON file.

## Run the first refresh

1. Open the repository's **Actions** tab.
2. Select **Refresh provider course catalogue**.
3. Choose **Run workflow**.
4. Open the run and confirm that all steps are green.
5. Check that GitHub Actions created a commit named **Refresh provider course catalogue**.

After that, it runs every Monday at 03:17 London time. It can still be run manually at any time.

## GitHub Pages notes

This package assumes the brochure is served from the repository root and the JSON is at `data/knowledge-academy-courses.json`.

When GitHub Pages uses a `/docs` folder instead:

- put the brochure in `docs/`;
- put the JSON in `docs/data/`;
- change the workflow's refresh command to:

```yaml
      - name: Refresh catalogue
        env:
          CATALOGUE_OUTPUT: docs/data/knowledge-academy-courses.json
        run: python scripts/update_courses.py
```

Also change the commit step paths from `data/knowledge-academy-courses.json` to `docs/data/knowledge-academy-courses.json`.

## Safety controls

The scraper does not overwrite the current JSON when:

- fewer than 150 courses are found;
- the catalogue unexpectedly drops by more than 45%;
- excluded project-management products appear;
- duplicate course URLs are produced;
- the provider request or XML parsing fails before validation.

The brochure also saves the last successful JSON in the browser. If a later request fails, it shows the saved catalogue and a warning rather than leaving the page empty.

## Course rules

Included categories focus on IT and useful connected skills, including Cisco, Microsoft, Azure, cyber security, cloud, data, AI, programming, DevOps, testing, business analysis and digital skills.

Excluded project-management products include PRINCE2, PMP, MSP, Scrum, SAFe, APM PMQ and Microsoft Project. AgilePM remains included.

Prices, scheduled dates and claimed availability are not copied. Those details must be confirmed during the DT&I Academy approval and booking process.
