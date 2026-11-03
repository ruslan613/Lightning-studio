# Gilil Supply — автономная ИИ-программа

Пайплайн светильника: **вход (фото/PDF/видео) → verify A↔B → DXF → паспорт + рендер → RFQ**.

## Модули

| Модуль | Роль |
|--------|------|
| **orchestrator** | План, очередь, verify-цикл, память (SQLite) |
| **design** | NL → `design_brief` (материалы, габариты, LED, стиль, варианты) |
| **cad3d** | Параметрическая модель + `geometry.json` / `viz_scene.json` |
| **engineering** | Анализ входа, ревизия, DXF, паспорт; week3: тепло/электрика/механика → `engineering_report` |
| **viz** | Промпт AI-рендера + 2D-превью (отдельно от `visualization/`) |
| **visualization** | `design_review` (правила Gilil), рендер CCT 3000–4000K |
| **automation** | RFQ поставщику, обновление каталога |
| **catalogs** | Таблица каталога (xlsx/csv) + HTML-фрагмент gilil_lighting |
| **sales** | Карточка товара + котировка RUB/CNY |

## Цепочка

1. Если есть `path` → `engineering.analyze_input`; иначе → `design.brief_from_goal` (NL → ТЗ)  
2. **Verify-цикл** (макс. 3 итерации, память `verify_iteration` / `design_remarks`):  
   - `visualization.design_review` — материалы, CCT, пропорции, стиль (люстра/бра)  
   - если не OK → `design.refine_brief` или `engineering.revise_from_review` + снова review  
   - если после 3 итераций не OK → `failed`  
3. `cad3d.build_parametric` → `cad3d.export_viz_spec`  
4. `engineering.export_dxf` — слои OUTLINE/HOLES/LED/NOTES  
5. `engineering.build_spec` — паспорт  
6. `visualization.render`  
7. `automation.make_rfq` → `automation.update_catalog`
8. `catalogs.build_catalog_table` + `site_fragment` → `sales.product_card` + `price_quote`

Полный цикл (без `--weekN`): verify + DXF/паспорт/рендер/RFQ **и** каталог/продажи.
Приёмка: `scripts/full_accept.py` → `ACCEPT_FULL=PASS`.

**Неделя 2:** `python -m orchestrator.cli run "…" --week2` — design → cad3d → `done`. Приёмка: `scripts/week2_accept.py`.

**Неделя 3:** `python -m orchestrator.cli run "…" --week3` — design → cad3d → eng.report → viz (prompt + preview_2d) → `done`. Приёмка: `scripts/week3_accept.py`.

**Неделя 4:** `python -m orchestrator.cli run "…" --week4` — week3 + catalogs (table + site_fragment) + sales (product_card + price_quote) → `done`. Приёмка: `scripts/week4_accept.py`.

Вход: NL-цель и/или `payload.path` + `input_type`.  
Артефакты: `design/design_brief.json`, `cad3d/geometry.json`, `engineering/engineering_report.*`, `viz/render_prompt.txt`, `viz/preview_2d.png`, `catalogs/catalog.xlsx|.csv`, `catalogs/site_fragment.html`, `sales/product_card.json|.md`, `sales/price_quote.json`. DWG — позже.

## Запуск

```bash
cd /workspace/artifacts/gilil_program
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m orchestrator.orchestrator
```

Демо: `data/samples/sconce_demo.png` → analyze → design_review (OK) → DXF → … → RFQ.

Несовместимый материал (`materials=["plastic"]`) → замечание → revise → повторный review → далее по цепочке.

## Единое приложение

**AI Lighting Studio** — нативное десктоп-приложение (отдельное окно, Electron), не веб-страница и не localhost.
Отдельная программа: никакой связи с Gilil On / Gilil Supply.

- `desktop/` — Electron: `main.js` (окно «AI Lighting Studio», запуск Python-бэкенда), `preload.js`, `renderer/` (UI, three.js вендорен в `renderer/vendor/`, без CDN).
- `app/backend.py` — stdio JSON-мост к `Orchestrator` (`python -m app`): `info`, `list_projects`, `create_project` (задача, пайплайн week2/3/4/full, режим автономности, файл фото/PDF/видео), `project` (задачи + статусы + артефакты + файлы), `set_autonomy`, `confirm`, `rerun_step` (повтор одного шага module.action), `rerun_pipeline`, `geometry`, `wait`. Пайплайн идёт в фоновом потоке, UI опрашивает статус.
- Вкладки: Обзор · Дизайн · 3D (three.js, вращение/зум) · Инженерия (отчёт + DXF) · Визуализация · Каталог (таблица, xlsx/csv, фрагмент сайта) · Продажи (карточка, RUB/CNY) · Режим автономности; «скоро»: Материалы, Светотехника, Производство, Расчёты, Поставщики, Контроль качества.
- В пайплайнах week3/week4 приложение добавляет шаг `engineering.export_dxf` (CLI не меняется).
- `shared/store.py`: переменная `ALS_DATA_DIR` переопределяет каталог данных (по умолчанию `data/`).

Запуск на Linux (dev): `./run_app.sh` (без `$DISPLAY` — через xvfb).
Сборка Windows: `cd desktop && npm install && scripts/prep-python-win.sh && npm run dist` → `desktop/dist/AI-Lighting-Studio-<ver>-portable.exe`.
В exe вшит embeddable CPython 3.13 (Windows x64) + колёса win_amd64 из `requirements.txt` → тот же Python-пайплайн, без установки Python. Данные на Windows: `%APPDATA%\AI Lighting Studio\data`.
Скриншоты: `desktop/screens/*.png` (режим `ALS_SCREENSHOTS=<dir>`).

## Ф0: проекты с версиями, установщик, CI (v0.5.0)

**Раскладка проекта** `data/projects/<id>/` (`ALS_DATA_DIR` переопределяет `data/`):
`project.json` (id, name, created_at, updated_at, current_version, fixture_type, author, app_version) ·
`versions/vN/files/…` неизменяемый снимок + `versions/vN/manifest.json` (sha256/size на файл, parent, message, timestamp, kind, restored_from, tree_sha256) ·
остальное — рабочая копия. Индекс: таблицы `als_project_meta`, `als_project_versions` в `projects.db` (создаются `IF NOT EXISTS`, старые таблицы не трогаются; старые проекты получают `project.json` при первом обращении).

- Пайплайн, завершившийся `done`, сам создаёт версию (`kind=pipeline`, без дублей).
- Откат (`checkout`) восстанавливает рабочую копию из vN и создаёт **новую** версию (`kind=rollback`), история не удаляется.
- `.alsproj` — zip: `alsproj.json` (метаданные, версии, строка оркестратора, артефакты) + `project/…`; при импорте проверяются sha256 всех снимков; занятый id → новый id.

CLI: `python -m projects list|create|show|rename|save -m|log|diff A [B]|checkout N|verify N|export ID DIR|import FILE`.
stdio-бэкенд: `save_version, list_versions, checkout_version, diff_versions, export_project, import_project, rename_project, verify_version`.
UI: вкладка **«Версии»** (история, «Сохранить версию», «Откатить», «Сравнить», переименование), кнопки «Экспорт/Импорт .alsproj».
Приёмка: `.venv/bin/python scripts/f0_accept.py` → `ACCEPT_F0_PROJECTS=PASS`.

**Установщик:** `desktop/installer/als.iss` (Inno Setup 6: Program Files, ярлыки меню Пуск/рабочего стола, деинсталлятор, RU+EN, иконка, ассоциация .alsproj; данные — `%APPDATA%\AI Lighting Studio\data`). Также NSIS в `package.json` (`npm run dist:all`, только Windows/wine).
**CI:** `.github/workflows/build-windows.yml` — windows-latest: приёмка → embedded Python → `npm ci` → portable+NSIS+dir → Inno Setup → artifacts → (опц.) Google Drive через `scripts/upload_drive.py` (секреты `GOOGLE_SERVICE_ACCOUNT_JSON`, `DRIVE_FOLDER_ID`).
