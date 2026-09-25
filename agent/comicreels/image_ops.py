"""Local, deterministic image operations for ComicReels."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
from typing import Iterable
import cv2
import numpy as np
from PIL import Image, ImageFilter

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def image_info(path: str | Path) -> tuple[int, int, str]:
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        return im.width, im.height, im.format or ""

def detect_panels(path: str | Path) -> list[dict]:
    """Best-effort local detector. Falls back to one full-frame panel when uncertain."""
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError("Không đọc được ảnh nguồn")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int,int,int,int,float]] = []
    min_area = w * h * 0.035
    max_area = w * h * 0.96
    for c in contours:
        x,y,cw,ch = cv2.boundingRect(c)
        area = cw * ch
        if area < min_area or area > max_area or cw < 80 or ch < 80:
            continue
        rectangularity = float(cv2.contourArea(c)) / max(1, area)
        if rectangularity < 0.35:
            continue
        candidates.append((x,y,cw,ch,rectangularity))
    candidates.sort(key=lambda b: b[2]*b[3], reverse=True)
    kept: list[tuple[int,int,int,int,float]] = []
    for box in candidates:
        x,y,cw,ch,_ = box
        duplicate = False
        for k in kept:
            kx,ky,kw,kh,_ = k
            ix=max(x,kx); iy=max(y,ky); ax=min(x+cw,kx+kw); ay=min(y+ch,ky+kh)
            inter=max(0,ax-ix)*max(0,ay-iy)
            if inter / max(1, min(cw*ch, kw*kh)) > 0.82:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    if len(kept) < 2 or len(kept) > 16:
        return [{"x":0,"y":0,"width":w,"height":h,"confidence":0.25,"display_order":0}]
    median_h = float(np.median([b[3] for b in kept]))
    kept.sort(key=lambda b: (round(b[1] / max(1.0, median_h * 0.45)), b[0]))
    return [
        {"x":int(x),"y":int(y),"width":int(cw),"height":int(ch),
         "confidence":round(min(0.95,max(0.3,score)),3),"display_order":i}
        for i,(x,y,cw,ch,score) in enumerate(kept)
    ]

def crop_panel(source_path: str | Path, bbox: dict, out_path: str | Path) -> str:
    with Image.open(source_path) as im:
        x,y,w,h = [int(bbox[k]) for k in ("x","y","width","height")]
        if x < 0 or y < 0 or x+w > im.width or y+h > im.height:
            raise ValueError("Panel bbox nằm ngoài ảnh nguồn")
        crop = im.crop((x,y,x+w,y+h))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        crop.save(out_path, format="PNG")
    return str(out_path)

def make_mask(size: tuple[int,int], boxes: Iterable[dict], out_path: str | Path, padding: int = 8) -> str:
    w,h=size
    mask=np.zeros((h,w),dtype=np.uint8)
    for b in boxes:
        x=max(0,int(b["x"])-padding); y=max(0,int(b["y"])-padding)
        x2=min(w,int(b["x"]+b["width"])+padding); y2=min(h,int(b["y"]+b["height"])+padding)
        cv2.rectangle(mask,(x,y),(x2,y2),255,-1)
    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(out_path),mask)
    return str(out_path)

def clean_with_mask(crop_path: str | Path, mask_path: str | Path, out_path: str | Path,
                    radius: int = 5) -> str:
    src=cv2.imread(str(crop_path),cv2.IMREAD_COLOR)
    mask=cv2.imread(str(mask_path),cv2.IMREAD_GRAYSCALE)
    if src is None or mask is None:
        raise ValueError("Không đọc được crop hoặc mask")
    if src.shape[:2] != mask.shape[:2]:
        raise ValueError("Mask không cùng kích thước crop")
    if int(mask.max()) == 0:
        cleaned=src.copy()
    else:
        generated=cv2.inpaint(src,mask,float(radius),cv2.INPAINT_TELEA)
        cleaned=src.copy()
        idx=mask>0
        cleaned[idx]=generated[idx]
    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(out_path),cleaned)
    return str(out_path)

def verticalize(clean_path: str | Path, out_path: str | Path) -> tuple[str, dict]:
    """Create exact 9:16 canvas without resizing source pixels."""
    with Image.open(clean_path).convert("RGB") as src:
        sw,sh=src.size
        target_w=sw
        target_h=math.ceil(target_w*16/9)
        if target_h < sh:
            target_h=sh
            target_w=math.ceil(target_h*9/16)
        units=math.ceil(max(target_w/9,target_h/16))
        tw,th=units*9,units*16
        scale=max(tw/sw,th/sh)
        bw,bh=max(1,round(sw*scale)),max(1,round(sh*scale))
        bg=src.resize((bw,bh),Image.Resampling.LANCZOS)
        left=max(0,(bw-tw)//2); top=max(0,(bh-th)//2)
        bg=bg.crop((left,top,left+tw,top+th)).filter(
            ImageFilter.GaussianBlur(radius=max(10,min(tw,th)//35))
        )
        x=(tw-sw)//2; y=(th-sh)//2
        bg.paste(src,(x,y))
        Path(out_path).parent.mkdir(parents=True,exist_ok=True)
        bg.save(out_path,format="PNG")
        return str(out_path), {
            "x":x,"y":y,"width":sw,"height":sh,
            "canvas_width":tw,"canvas_height":th,
        }

def verify_protected_region(clean_path: str | Path, vertical_path: str | Path, box: dict) -> bool:
    with Image.open(clean_path).convert("RGB") as src, Image.open(vertical_path).convert("RGB") as out:
        x,y,w,h=[int(box[k]) for k in ("x","y","width","height")]
        region=out.crop((x,y,x+w,y+h))
        return np.array_equal(np.asarray(src),np.asarray(region))
