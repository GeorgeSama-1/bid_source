from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bid_knowledge.service.result_browser import ResultBrowser, ResultNotFoundError


BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Bid Result Browser")
browser = ResultBrowser(BASE_DIR / "outputs")


@app.get("/api/runs")
def list_runs() -> dict[str, object]:
    return {"runs": browser.list_runs()}


@app.get("/api/runs/{run_name}/modules/tree")
def get_module_tree(run_name: str) -> dict[str, object]:
    try:
        return browser.get_module_tree(run_name)
    except ResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_name}/materials/meta")
def get_material_meta(run_name: str, path: str = Query(...)) -> dict[str, object]:
    try:
        return browser.get_material_meta(run_name, path)
    except ResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_name}/materials/ordered")
def get_ordered_material(run_name: str, path: str = Query(...)) -> dict[str, object]:
    try:
        return browser.get_ordered_material(run_name, path)
    except ResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_name}/items/detail")
def get_item_detail(
    run_name: str,
    material_path: str = Query(...),
    item_type: str = Query(...),
    item_name: str = Query(...),
) -> object:
    try:
        return browser.get_item_detail(run_name, material_path, item_type, item_name)
    except ResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_name}/images")
def get_image(run_name: str, path: str = Query(...)) -> FileResponse:
    try:
        file_path, media_type = browser.get_image_file(run_name, path)
    except ResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(file_path, media_type=media_type)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
