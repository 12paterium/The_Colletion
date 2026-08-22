# Meme Sorting Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a one-request image pipeline that converts WebP, generates a Chinese mark, classifies into four folders, and stops inside the selected sorting directory.

**Architecture:** `scripts.main` is a thin entry point over the deep `sorter.sort_directory` interface. `sorter` coordinates deterministic conversion and moves, while `marker` owns the only model request and `utils` owns shared file primitives; no history or final-library automation is introduced.

**Tech Stack:** Python 3.12, OpenAI Python SDK 2.x, Pillow 10.x, tqdm 4.x, standard-library `unittest`

**Spec:** `docs/superpowers/specs/2026-08-22-meme-sorting-pipeline-design.md`

## Global Constraints

- Production processing is limited to direct child images of repository `sorting/`.
- Output categories are exactly `梗图`, `表情`, `史`, and `其他`.
- Each successfully analyzed image makes exactly one model request returning `mark` and `category` together.
- No history, duplicate database, final-library move, recursive production scan, or real API call in automated tests.
- Existing media and user-owned worktree changes must not be restored, moved, staged, or modified.
- The live 50-image run uses copied files in `sorting/.validation`, reports results, and removes only that verified directory.

---

### Task 1: Shared image and path primitives

**Files:**
- Create: `scripts/__init__.py`
- Modify: `scripts/utils.py`
- Create: `tests/__init__.py`
- Create: `tests/test_utils.py`

**Interfaces:**
- Produces: `IMAGE_EXTENSIONS`, `CATEGORIES`, `SORTING_DIR`, `discover_images(directory: Path) -> list[Path]`, `image_data_url(path: Path) -> str`, `clean_filename(text: str) -> str`, `get_unique_path(directory: Path, filename: str) -> Path`, and `RequestPacer.wait() -> None`.

- [ ] **Step 1: Write failing utility tests**

```python
class UtilsTests(unittest.TestCase):
    def test_discover_images_only_returns_direct_supported_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.JPG").write_bytes(b"a")
            (root / "video.mp4").write_bytes(b"v")
            (root / "梗图").mkdir()
            (root / "梗图" / "nested.png").write_bytes(b"n")
            self.assertEqual([path.name for path in discover_images(root)], ["a.JPG"])

    def test_clean_filename_removes_windows_illegal_characters(self):
        self.assertEqual(clean_filename('  警察:*  你继续说?.  '), "警察 你继续说")
```

- [ ] **Step 2: Run tests and confirm missing imports fail**

Run: `python -m unittest tests.test_utils -v`

Expected: FAIL because `scripts.utils` does not yet provide the interfaces.

- [ ] **Step 3: Implement the shared primitives**

```python
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
CATEGORIES = ("梗图", "表情", "史", "其他")
SORTING_DIR = Path(__file__).resolve().parents[1] / "sorting"

def discover_images(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
```

Implement MIME-correct data URLs, filename sanitization with a non-empty check, collision suffixes, and the existing non-blocking request pacer.

- [ ] **Step 4: Run the utility tests**

Run: `python -m unittest tests.test_utils -v`

Expected: PASS.

- [ ] **Step 5: Commit the utility module**

```bash
git add scripts/__init__.py scripts/utils.py tests/__init__.py tests/test_utils.py
git commit -m "refactor: extract image utilities"
```

### Task 2: Safe static and animated WebP conversion

**Files:**
- Create: `scripts/converter.py`
- Create: `tests/test_converter.py`

**Interfaces:**
- Consumes: `get_unique_path(directory, filename)` from Task 1.
- Produces: `convert_webp(image_path: Path) -> Path`; non-WebP input is returned unchanged, successful WebP conversion returns a PNG/APNG path and removes the source only after verification.

- [ ] **Step 1: Write failing conversion tests**

```python
class ConverterTests(unittest.TestCase):
    def test_static_webp_becomes_png(self):
        source = self.root / "static.webp"
        Image.new("RGBA", (4, 4), "red").save(source, "WEBP")
        result = convert_webp(source)
        self.assertEqual(result.suffix, ".png")
        self.assertTrue(result.exists())
        self.assertFalse(source.exists())

    def test_animated_webp_preserves_frame_count(self):
        source = self.root / "animated.webp"
        frames = [Image.new("RGBA", (4, 4), color) for color in ("red", "blue")]
        frames[0].save(source, "WEBP", save_all=True, append_images=frames[1:], duration=[80, 120], loop=2)
        result = convert_webp(source)
        with Image.open(result) as converted:
            self.assertEqual(converted.n_frames, 2)
            self.assertEqual(converted.info.get("loop"), 2)
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run: `python -m unittest tests.test_converter -v`

Expected: FAIL importing `scripts.converter`.

- [ ] **Step 3: Implement verified temporary conversion**

```python
def convert_webp(image_path: Path) -> Path:
    if image_path.suffix.lower() != ".webp":
        return image_path
    target = get_unique_path(image_path.parent, f"{image_path.stem}.png")
    temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp.png")
    # Decode all frames, save PNG/APNG, reopen and verify frame count,
    # atomically replace the target, then unlink the WebP.
    return target
```

On every exception, unlink only the exact temporary path and leave the WebP in place.

- [ ] **Step 4: Run conversion tests**

Run: `python -m unittest tests.test_converter -v`

Expected: PASS for static, animated, collision, non-WebP, and corrupt-WebP cases.

- [ ] **Step 5: Commit the converter**

```bash
git add scripts/converter.py tests/test_converter.py
git commit -m "feat: convert webp images safely"
```

### Task 3: One-request structured image decision

**Files:**
- Modify: `scripts/marker.py`
- Create: `tests/test_marker.py`

**Interfaces:**
- Consumes: `CATEGORIES`, `RequestPacer`, `clean_filename`, and `image_data_url` from Task 1.
- Produces: immutable `ImageDecision(mark: str, category: str)`, `parse_decision(content: str) -> ImageDecision`, `load_provider() -> tuple[Provider, str, str]`, and `analyze_image(client, model, image_path, pacer) -> tuple[ImageDecision, int]`.

- [ ] **Step 1: Write failing parser and request tests**

```python
class MarkerTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_decision_validates_category(self):
        decision = parse_decision('{"mark":"警察 你继续说","category":"表情"}')
        self.assertEqual(decision, ImageDecision("警察 你继续说", "表情"))
        with self.assertRaises(ValueError):
            parse_decision('{"mark":"名字","category":"未知"}')

    async def test_analyze_image_requests_json_once(self):
        decision, status = await analyze_image(fake_client, "model", image_path, FakePacer())
        self.assertEqual(fake_client.calls, 1)
        self.assertEqual(status, 200)
```

- [ ] **Step 2: Run tests and confirm the old marker interface fails**

Run: `python -m unittest tests.test_marker -v`

Expected: FAIL because the old module returns plain names and performs file mutations.

- [ ] **Step 3: Replace marker with the structured interface**

```python
@dataclass(frozen=True)
class ImageDecision:
    mark: str
    category: str

def parse_decision(content: str) -> ImageDecision:
    payload = json.loads(content)
    mark = clean_filename(payload["mark"])
    category = payload["category"]
    if category not in CATEGORIES:
        raise ValueError(f"未知分类：{category}")
    return ImageDecision(mark=mark, category=category)
```

The prompt includes the four ordered rules and asks for exactly `mark` and `category`; the request uses `response_format={"type": "json_object"}` and performs no rename, move, retry repair, or history write.

- [ ] **Step 4: Run marker tests**

Run: `python -m unittest tests.test_marker -v`

Expected: PASS.

- [ ] **Step 5: Commit marker refactor**

```bash
git add scripts/marker.py tests/test_marker.py
git commit -m "refactor: return structured image decisions"
```

### Task 4: Sorting orchestration and thin entry point

**Files:**
- Modify: `scripts/sorter.py`
- Create: `scripts/main.py`
- Create: `tests/test_sorter.py`

**Interfaces:**
- Consumes: `convert_webp`, `ImageDecision`, marker provider/request functions, and Task 1 primitives.
- Produces: `ImageAnalyzer = Callable[[Path], Awaitable[tuple[ImageDecision, int]]]`, `SortItemResult`, `SortSummary`, and `sort_directory(directory: Path = SORTING_DIR, analyzer: ImageAnalyzer | None = None) -> SortSummary`.

- [ ] **Step 1: Write failing orchestration tests**

```python
class SorterTests(unittest.IsolatedAsyncioTestCase):
    async def test_moves_each_decision_to_its_category(self):
        source = self.root / "input.jpg"
        source.write_bytes(b"image")

        async def fake_analyzer(path):
            return ImageDecision("新名字", "梗图"), 200

        summary = await sort_directory(self.root, analyzer=fake_analyzer)
        self.assertEqual(summary.succeeded, 1)
        self.assertTrue((self.root / "梗图" / "新名字.jpg").exists())

    async def test_failure_leaves_input_in_root(self):
        source = self.root / "input.jpg"
        source.write_bytes(b"image")

        async def failing_analyzer(path):
            raise RuntimeError("request failed")
        summary = await sort_directory(self.root, analyzer=failing_analyzer)
        self.assertEqual(summary.failed, 1)
        self.assertTrue(source.exists())
```

- [ ] **Step 2: Run tests and confirm the empty sorter fails**

Run: `python -m unittest tests.test_sorter -v`

Expected: FAIL because `sort_directory` is absent.

- [ ] **Step 3: Implement the deep sorter module**

```python
@dataclass(frozen=True)
class SortItemResult:
    source_path: Path
    final_path: Path | None
    decision: ImageDecision | None
    status_code: int | str
    error: str | None

@dataclass(frozen=True)
class SortSummary:
    results: tuple[SortItemResult, ...]

    @property
    def succeeded(self) -> int:
        return sum(result.error is None for result in self.results)
```

Create the four directories, discover only direct images, convert WebP before analysis, run at most six model tasks concurrently, lock collision selection plus move, leave failures at the input root, and return every item result for validation.

- [ ] **Step 4: Add the thin module entry point**

```python
def main() -> None:
    try:
        asyncio.run(sort_directory())
    except (FileNotFoundError, ValueError) as exc:
        logger.error("无法启动：%s", exc)
        raise SystemExit(1) from exc
```

- [ ] **Step 5: Run all automated tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS with no real network access and no repository media changes.

- [ ] **Step 6: Commit the sorter and entry point**

```bash
git add scripts/sorter.py scripts/main.py tests/test_sorter.py
git commit -m "feat: classify and sort images"
```

### Task 5: Documentation and obsolete history cleanup

**Files:**
- Modify: `README.md`
- Create: `AGENTS.md`
- Create: `requirements.txt`
- Delete: `sort_history.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the completed production command `python -m scripts.main` and environment names from marker.
- Produces: user setup/operation documentation and agent safety rules; no runtime interfaces.

- [ ] **Step 1: Extend README without removing the existing preface**

Document `pip install -r requirements.txt`, provider keys, the four classification rules, direct-child-only processing, WebP/APNG behavior, failure retry semantics, and `python -m scripts.main`.

- [ ] **Step 2: Add repository agent rules**

State that agents must not modify archive media, the protected manual-classification directory, or real `sorting/` images during tests; tests use temporary directories and fake clients; secrets are never printed or committed; final-library moves remain human-only.

- [ ] **Step 3: Remove only obsolete history artifacts**

Delete tracked `sort_history.json` and remove only its `.gitignore` line. Do not stage user-owned deleted/moved media or `.idea/workspace.xml`.

- [ ] **Step 4: Verify docs and tests**

Run: `python -m unittest discover -s tests -v`

Expected: PASS. Also run `git diff --check` and inspect `git status --short` to ensure only intended code/docs/history paths are staged.

- [ ] **Step 5: Commit documentation and cleanup**

```bash
git add README.md AGENTS.md requirements.txt .gitignore sort_history.json
git commit -m "docs: document image sorting workflow"
```

### Task 6: Live 50-image validation and cleanup

**Files:**
- Create: `docs/validation/2026-08-23-sorting-sample.md`
- Temporary create/delete: `sorting/.validation/`
- Temporary create/delete: `tests/_live_validation.py`

**Interfaces:**
- Consumes: `sort_directory(validation_directory)` and the existing classified source folders.
- Produces: a persistent Markdown comparison report; all copied validation images and the one-off harness are removed before completion.

- [ ] **Step 1: Create a one-off validation harness**

Use `random.Random(20260823)` and quotas `弔图: 13`, `表情: 13`, `史: 12`, `杂篇: 12`. Copy selected files into `sorting/.validation`, store each source SHA-256 and expected category, and never mutate sources.

- [ ] **Step 2: Run the real model pipeline**

Run: `python tests/_live_validation.py`

Expected: 50 copied images are converted/analyzed once each and moved inside `.validation` when successful. If the sandbox blocks the configured provider, rerun the same command with network approval.

- [ ] **Step 3: Generate the comparison report**

Write a row per image containing source name, generated name, expected category, actual category, match, and error. Include total/per-category agreement, successful/failed counts, source-hash verification, WebP frame verification, and path containment/overwrite checks.

- [ ] **Step 4: Remove only validation artifacts**

In `finally`, resolve the cleanup target and require exact equality with `<repo>/sorting/.validation`; reject symlinks and Windows junctions, then delete that directory. Remove `tests/_live_validation.py` with `apply_patch`. Confirm the 50 sources still exist with unchanged SHA-256.

- [ ] **Step 5: Run final verification**

Run: `python -m unittest discover -s tests -v`

Run: `Test-Path -LiteralPath '.\sorting\.validation'`

Expected: all unit tests PASS and `Test-Path` returns `False`.

- [ ] **Step 6: Commit the report only**

```bash
git add docs/validation/2026-08-23-sorting-sample.md
git commit -m "test: report live sorting sample"
```
