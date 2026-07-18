from __future__ import annotations

import copy
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Tuple

from epuboverlay.preprocessors.base import BasePreprocessor, DocumentSection, ends_with_terminal_punctuation

# --- Helpers ---

import re

# Strict regex matching:
# 1. Keywords followed optionally by numbers/numerals/words (no trailing generic words)
# 2. Standalone major section titles
HEADING_KEYWORDS_RE = re.compile(
    r"^(?:PART|CHAPTER|PRINCIPLE|BOOK|SECTION)(?:\s+(?:[0-9IVXLC]+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|FIRST|SECOND|THIRD|FOURTH|FIFTH))?$|^(?:PREFACE|INTRODUCTION|FOREWORD|NOTES|EPILOGUE|AFTERWORD|BIBLIOGRAPHY|INDEX|CONTENTS)$",
    re.IGNORECASE
)

def clean_tag(tag: str) -> str:
    """Strip XML namespace prefixes from tags."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def find_heuristic_anchors(xhtml_root: ET.Element) -> List[Tuple[str, str]]:
    """Scans the DOM body for elements that look like headings.
    
    Assigns a dynamic id to them if they don't have one, and returns a list of (id, title).
    """
    body = xhtml_root.find(".//{*}body")
    if body is None:
        return []
        
    all_elements = list(body.iter())
    candidates = []
    current_pos = 0
    
    for el in all_elements:
        tag = clean_tag(el.tag)
        if tag == "p":
            text = "".join(el.itertext()).strip()
            # Normalize whitespace
            text_norm = " ".join(text.split())
            # Merge spaced-out single letters (e.g. "O N E" -> "ONE", "P A R T" -> "PART")
            text_norm = re.sub(r'(?<=\b[a-zA-Z])\s+(?=[a-zA-Z]\b)', '', text_norm)
            
            current_pos += len(text_norm)
            if 3 <= len(text_norm) <= 120 and HEADING_KEYWORDS_RE.match(text_norm):
                candidates.append({
                    "element": el,
                    "text": text_norm,
                    "pos": current_pos
                })
                
    filtered = []
    for idx, cand in enumerate(candidates):
        # Discard list items close to the next candidate
        if idx < len(candidates) - 1:
            next_cand = candidates[idx + 1]
            dist = next_cand["pos"] - cand["pos"]
            if dist < 500:
                continue
                
        # Discard list items close to the previous kept candidate
        if filtered:
            last_kept = filtered[-1]
            if cand["pos"] - last_kept["pos"] < 500:
                continue
                
        el = cand["element"]
        eid = el.attrib.get("id") or el.attrib.get("name")
        if not eid:
            eid = f"dyn_heading_{len(filtered)}"
            el.attrib["id"] = eid
            
        filtered.append({
            "id": eid,
            "text": cand["text"],
            "pos": cand["pos"]
        })
        
    return [(c["id"], c["text"]) for c in filtered]



def merge_consecutive_paragraphs(parent: ET.Element) -> None:
    """Recursively merge consecutive <p> tags with matching classes if they wrap continuous sentences.
    
    Handles Calibre-style conversions where <br> tags and empty <p> elements
    are interspersed between visual line-wrap paragraphs.
    """
    structural_blocks = {"div", "section", "article", "aside", "body", "html"}
    
    def _is_skippable(el: ET.Element) -> bool:
        """Return True if the element is a spacer that should be skipped during merge."""
        tag = clean_tag(el.tag)
        # <br> elements are always skippable spacers
        if tag == "br":
            return True
        # Empty <p> elements (no text content at all) are skippable spacers
        if tag == "p":
            text = "".join(el.itertext()).strip()
            if not text:
                return True
        return False
    
    def _find_next_p(parent_el: ET.Element, start_idx: int) -> "tuple[int, ET.Element] | None":
        """Find the next non-empty <p> element after start_idx, skipping spacers."""
        children = list(parent_el)
        j = start_idx
        while j < len(children):
            child = children[j]
            tag = clean_tag(child.tag)
            if tag == "p":
                text = "".join(child.itertext()).strip()
                if text:
                    return j, child
                # Empty <p> — skip it
            elif not _is_skippable(child):
                # Hit a non-skippable, non-<p> element — stop searching
                return None
            j += 1
        return None
    
    i = 0
    while i < len(parent):
        child = parent[i]
        tag1 = clean_tag(child.tag)
        
        if tag1 == "p":
            text1 = "".join(child.itertext()).strip()
            class1 = child.attrib.get("class", "")
            
            # Only attempt merge if this <p> has text and doesn't end with terminal punctuation
            if text1 and not ends_with_terminal_punctuation(text1):
                # Look ahead for the next non-empty <p> sibling, skipping <br> and empty <p>
                result = _find_next_p(parent, i + 1)
                if result is not None:
                    next_idx, next_p = result
                    class2 = next_p.attrib.get("class", "")
                    
                    if class1 == class2:
                        # Remove all spacer elements between child and next_p
                        elements_to_remove = []
                        for k in range(i + 1, next_idx):
                            elements_to_remove.append(parent[k])
                        for el in elements_to_remove:
                            parent.remove(el)
                        
                        # After removals, next_p is now at position i+1
                        # Merge next_p text into child
                        if len(child) > 0:
                            last_sub = child[-1]
                            last_sub.tail = (last_sub.tail or "") + " "
                        else:
                            child.text = (child.text or "") + " "
                        
                        if next_p.text:
                            if len(child) > 0:
                                last_sub = child[-1]
                                last_sub.tail = (last_sub.tail or "") + next_p.text
                            else:
                                child.text = (child.text or "") + next_p.text
                                
                        for sub in list(next_p):
                            next_p.remove(sub)
                            child.append(sub)
                            
                        if next_p.tail:
                            if len(child) > 0:
                                child[-1].tail = (child[-1].tail or "") + next_p.tail
                            else:
                                child.text = (child.text or "") + next_p.tail
                                
                        parent.remove(next_p)
                        continue  # Re-check the same child for further merges
        
        if tag1 in structural_blocks:
            merge_consecutive_paragraphs(child)
            
        i += 1



def split_xhtml_by_anchors(xhtml_root: ET.Element, anchors: List[str]) -> List[ET.Element]:
    """Splits an XHTML DOM root into multiple roots based on a list of anchor element IDs."""
    if not anchors:
        return [xhtml_root]
        
    body = xhtml_root.find(".//{*}body")
    if body is None:
        return [xhtml_root]
        
    elements_in_order = list(body.iter())
    anchor_elements = {}
    for el in elements_in_order:
        eid = el.attrib.get("id")
        if eid in anchors:
            anchor_elements[eid] = el
            
    if not anchor_elements:
        return [xhtml_root]
        
    active_anchors = [a for a in anchors if a in anchor_elements]
    num_sections = len(active_anchors) + 1
    
    element_to_section = {}
    current_section = 0
    
    for el in elements_in_order:
        if current_section < len(active_anchors):
            next_anchor_id = active_anchors[current_section]
            if el is anchor_elements[next_anchor_id]:
                current_section += 1
        element_to_section[el] = current_section
        
    roots = []
    for sec_idx in range(num_sections):
        new_root = copy.deepcopy(xhtml_root)
        new_body = new_root.find(".//{*}body")
        
        def prune_element(el, original_el_map) -> bool:
            orig_el = original_el_map.get(el)
            if orig_el is None:
                return False
                
            if len(el) == 0:
                return element_to_section.get(orig_el, 0) == sec_idx
                
            kept_children = []
            for child in list(el):
                if prune_element(child, original_el_map):
                    kept_children.append(child)
                else:
                    el.remove(child)
                    
            return len(kept_children) > 0 or element_to_section.get(orig_el, 0) == sec_idx
            
        original_body_elements = list(body.iter())
        copied_body_elements = list(new_body.iter())
        copied_to_original = dict(zip(copied_body_elements, original_body_elements))
        
        prune_element(new_body, copied_to_original)
        roots.append(new_root)
        
    return roots


def parse_epub_toc_filesystem(opf_dir: Path, opf_root: ET.Element) -> Tuple[Dict[str, str], Dict[str, List[Tuple[str, str]]]]:
    """Parse NAV or NCX from a local directory workspace.
    
    Returns (toc_map, anchor_map).
    """
    toc_map: Dict[str, str] = {}
    anchor_map: Dict[str, List[Tuple[str, str]]] = {}
    
    # Find NAV href
    nav_href = None
    manifest_items = opf_root.findall(".//{*}manifest/{*}item")
    for item in manifest_items:
        properties = item.attrib.get("properties", "")
        if "nav" in properties.split():
            nav_href = item.attrib.get("href")
            break
            
    if nav_href:
        try:
            nav_path = opf_dir / nav_href
            if nav_path.exists():
                nav_content = nav_path.read_bytes()
                from epuboverlay.pipeline import replace_html_entities
                nav_content = replace_html_entities(nav_content.decode("utf-8", errors="ignore")).encode("utf-8")
                nav_root = ET.fromstring(nav_content)
                nav_dir = nav_path.parent
                
                for a_el in nav_root.findall(".//{*}a"):
                    href = a_el.attrib.get("href", "").strip()
                    if href:
                        clean_href = href.split("#")[0]
                        anchor = href.split("#")[1] if "#" in href else ""
                        resolved_href = os.path.relpath(nav_dir / clean_href, opf_dir).replace("\\", "/")
                        title = "".join(a_el.itertext()).strip()
                        if title:
                            toc_map[resolved_href] = title
                            anchor_map.setdefault(resolved_href, []).append((anchor, title))
        except Exception:
            pass
            
    if not toc_map:
        # Fallback to NCX
        ncx_href = None
        for item in manifest_items:
            media_type = item.attrib.get("media-type", "")
            if media_type == "application/x-dtbncx+xml":
                ncx_href = item.attrib.get("href")
                break
        if ncx_href:
            try:
                ncx_path = opf_dir / ncx_href
                if ncx_path.exists():
                    ncx_content = ncx_path.read_bytes()
                    ncx_root = ET.fromstring(ncx_content)
                    ncx_dir = ncx_path.parent
                    
                    for nav_point in ncx_root.findall(".//{*}navPoint"):
                        content_el = nav_point.find("{*}content")
                        label_el = nav_point.find(".//{*}navLabel/{*}text")
                        if content_el is not None and label_el is not None:
                            src = content_el.attrib.get("src", "").strip()
                            text = (label_el.text or "").strip()
                            if src and text:
                                clean_src = src.split("#")[0]
                                anchor = src.split("#")[1] if "#" in src else ""
                                resolved_src = os.path.relpath(ncx_dir / clean_src, opf_dir).replace("\\", "/")
                                toc_map[resolved_src] = text
                                anchor_map.setdefault(resolved_src, []).append((anchor, text))
            except Exception:
                pass
                
    return toc_map, anchor_map


def update_nav_ncx(workspace_root: Path, opf_dir: Path, split_map: Dict[str, Dict[str, str]]) -> None:
    """Updates NAV and NCX references in the workspace to point to the newly split XHTML files.
    
    split_map maps: original_html_rel_path -> { anchor: new_html_rel_path }
    """
    for file_path in workspace_root.rglob("*"):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if suffix not in (".xhtml", ".html", ".ncx"):
            continue
            
        try:
            content = file_path.read_bytes()
            if suffix in (".xhtml", ".html"):
                from epuboverlay.pipeline import replace_html_entities
                content = replace_html_entities(content.decode("utf-8", errors="ignore")).encode("utf-8")
                
            root = ET.fromstring(content)
        except Exception:
            continue
            
        modified = False
        file_rel_dir = Path(os.path.relpath(file_path.parent, opf_dir))
        
        # 1. Update NAV anchors (<a> tags)
        for a_el in root.findall(".//{*}a"):
            href = a_el.attrib.get("href", "").strip()
            if href:
                clean_href = href.split("#")[0]
                anchor = href.split("#")[1] if "#" in href else ""
                
                target_rel_path = os.path.normpath(file_rel_dir / clean_href).replace("\\", "/").lstrip("./").lstrip("/")
                if target_rel_path in split_map:
                    anchor_to_new = split_map[target_rel_path]
                    new_rel_path = None
                    if anchor in anchor_to_new:
                        new_rel_path = anchor_to_new[anchor]
                    elif "" in anchor_to_new:
                        new_rel_path = anchor_to_new[""]
                        
                    if new_rel_path:
                        rel_to_file = os.path.relpath(opf_dir / new_rel_path, file_path.parent).replace("\\", "/")
                        a_el.attrib["href"] = rel_to_file
                        modified = True
                        
        # 2. Update NCX anchors (<content> tags)
        for content_el in root.findall(".//{*}content"):
            src = content_el.attrib.get("src", "").strip()
            if src:
                clean_src = src.split("#")[0]
                anchor = src.split("#")[1] if "#" in src else ""
                
                target_rel_path = os.path.normpath(file_rel_dir / clean_src).replace("\\", "/").lstrip("./").lstrip("/")
                if target_rel_path in split_map:
                    anchor_to_new = split_map[target_rel_path]
                    new_rel_path = None
                    if anchor in anchor_to_new:
                        new_rel_path = anchor_to_new[anchor]
                    elif "" in anchor_to_new:
                        new_rel_path = anchor_to_new[""]
                        
                    if new_rel_path:
                        rel_to_file = os.path.relpath(opf_dir / new_rel_path, file_path.parent).replace("\\", "/")
                        content_el.attrib["src"] = rel_to_file
                        modified = True
                        
        if modified:
            try:
                if suffix == ".ncx":
                    from epuboverlay.pipeline import serialize_opf
                    file_path.write_bytes(serialize_opf(root))
                else:
                    from epuboverlay.pipeline import serialize_xhtml
                    file_path.write_bytes(serialize_xhtml(root, content))
            except Exception:
                pass


def _find_element_title(root_el: ET.Element, default_title: str) -> str:
    title_el = root_el.find(".//{*}title")
    heading_el = root_el.find(".//{*}h1")
    if heading_el is None:
        heading_el = root_el.find(".//{*}h2")
    if heading_el is not None and "".join(heading_el.itertext()).strip():
        return "".join(heading_el.itertext()).strip()
    elif title_el is not None and "".join(title_el.itertext()).strip():
        return "".join(title_el.itertext()).strip()
    return default_title


def regenerate_nav_file(nav_path: Path, new_toc_entries: List[Tuple[str, str]], opf_dir: Path) -> None:
    try:
        content = nav_path.read_bytes()
        from epuboverlay.pipeline import replace_html_entities, serialize_xhtml
        content_decoded = replace_html_entities(content.decode("utf-8", errors="ignore"))
        root = ET.fromstring(content_decoded.encode("utf-8"))
        
        # Find nav element
        nav_el = None
        for nav in root.findall(".//{*}nav"):
            # Check if it is a TOC nav
            epub_type = nav.attrib.get("{http://www.idpf.org/2007/ops}type") or nav.attrib.get("epub:type")
            if epub_type == "toc" or not epub_type:
                nav_el = nav
                break
        
        if nav_el is None:
            # Create a new nav element in the body
            body = root.find(".//{*}body")
            if body is not None:
                nav_el = ET.Element("{http://www.w3.org/1999/xhtml}nav", attrib={
                    "{http://www.idpf.org/2007/ops}type": "toc",
                    "id": "toc"
                })
                h1 = ET.Element("{http://www.w3.org/1999/xhtml}h1")
                h1.text = "Table of Contents"
                nav_el.append(h1)
                body.append(nav_el)
        
        if nav_el is not None:
            # Remove any existing ol/ul lists inside nav_el
            for ol in list(nav_el.findall(".//{*}ol")) + list(nav_el.findall(".//{*}ul")):
                nav_el.remove(ol)
            
            # Create a new ol element
            ol_el = ET.Element("{http://www.w3.org/1999/xhtml}ol")
            nav_dir = nav_path.parent
            for href, title in new_toc_entries:
                # Calculate relative path from NAV file to target
                resolved_href = os.path.relpath(opf_dir / href, nav_dir).replace("\\", "/")
                li_el = ET.Element("{http://www.w3.org/1999/xhtml}li")
                a_el = ET.Element("{http://www.w3.org/1999/xhtml}a", attrib={"href": resolved_href})
                a_el.text = title
                li_el.append(a_el)
                ol_el.append(li_el)
            nav_el.append(ol_el)
            
            # Write back
            nav_path.write_bytes(serialize_xhtml(root, content))
    except Exception as e:
        print(f"Error regenerating NAV file: {e}")


def regenerate_ncx_file(ncx_path: Path, new_toc_entries: List[Tuple[str, str]], opf_dir: Path) -> None:
    try:
        content = ncx_path.read_bytes()
        from epuboverlay.pipeline import serialize_opf
        root = ET.fromstring(content)
        
        # Find navMap element
        navmap_el = root.find(".//{*}navMap")
        if navmap_el is None:
            navmap_el = ET.Element("{http://www.daisy.org/z3986/2005/ncx/}navMap")
            root.append(navmap_el)
        else:
            # Clear existing children
            for child in list(navmap_el):
                navmap_el.remove(child)
        
        ncx_dir = ncx_path.parent
        for idx, (href, title) in enumerate(new_toc_entries):
            resolved_href = os.path.relpath(opf_dir / href, ncx_dir).replace("\\", "/")
            
            navpoint = ET.Element("{http://www.daisy.org/z3986/2005/ncx/}navPoint", attrib={
                "id": f"navPoint-{idx + 1}",
                "playOrder": str(idx + 1)
            })
            navlabel = ET.Element("{http://www.daisy.org/z3986/2005/ncx/}navLabel")
            text_el = ET.Element("{http://www.daisy.org/z3986/2005/ncx/}text")
            text_el.text = title
            navlabel.append(text_el)
            
            content_el = ET.Element("{http://www.daisy.org/z3986/2005/ncx/}content", attrib={
                "src": resolved_href
            })
            
            navpoint.append(navlabel)
            navpoint.append(content_el)
            navmap_el.append(navpoint)
            
        ncx_path.write_bytes(serialize_opf(root))
    except Exception as e:
        print(f"Error regenerating NCX file: {e}")


def preprocess_epub_workspace(workspace_dir: Path) -> None:
    """Preprocesses an extracted EPUB workspace.
    
    1. Standardizes namespace declarations.
    2. Runs paragraph line-wrap merging on all XHTML documents.
    3. Splits XHTML documents by TOC anchors.
    4. Updates the OPF (manifest + spine) and NAV/NCX files.
    """
    from epuboverlay.pipeline import replace_html_entities, serialize_opf, serialize_xhtml
    
    container_path = workspace_dir / "META-INF/container.xml"
    if not container_path.exists():
        return
        
    container_tree = ET.parse(container_path)
    rootfile = container_tree.find(".//{*}rootfile")
    if rootfile is None:
        return
        
    opf_rel_path = rootfile.attrib.get("full-path")
    if not opf_rel_path:
        return
        
    opf_path = workspace_dir / opf_rel_path
    opf_dir = opf_path.parent
    
    opf_tree = ET.parse(opf_path)
    opf_root = opf_tree.getroot()
    
    toc_map, anchor_map = parse_epub_toc_filesystem(opf_dir, opf_root)
    use_heuristics = (len(anchor_map) <= 1)

    nav_href = None
    manifest_items_list = opf_root.findall(".//{*}manifest/{*}item")
    for item in manifest_items_list:
        properties = item.attrib.get("properties", "")
        if "nav" in properties.split():
            nav_href = item.attrib.get("href")
            break
    
    manifest_node = opf_root.find(".//{*}manifest")
    spine_node = opf_root.find(".//{*}spine")
    if manifest_node is None or spine_node is None:
        return
        
    manifest_items: Dict[str, Dict] = {}
    for item in manifest_node.findall(".//{*}item"):
        item_id = item.attrib.get("id", "")
        if item_id:
            manifest_items[item_id] = {
                "href": item.attrib.get("href", ""),
                "element": item
            }
            
    split_map: Dict[str, Dict[str, str]] = {}
    original_itemrefs = list(spine_node.findall(".//{*}itemref"))
    
    for itemref in original_itemrefs:
        idref = itemref.attrib.get("idref", "")
        item_data = manifest_items.get(idref)
        if not item_data:
            continue
            
        href = item_data["href"]
        item_el = item_data["element"]
        if item_el.attrib.get("media-type") != "application/xhtml+xml":
            continue
            
        html_path = (opf_dir / href).resolve()
        rel_html_path = os.path.relpath(html_path, opf_dir).replace("\\", "/")
        
        if not html_path.exists():
            continue
            
        try:
            content = html_path.read_bytes()
            xhtml_root = ET.fromstring(
                replace_html_entities(content.decode("utf-8", errors="ignore")).encode("utf-8")
            )
        except Exception:
            continue
            
        # Detect heuristic headings BEFORE merging paragraphs, otherwise the
        # merger joins heading text (e.g. "PART TWO") with neighbors and destroys
        # the pattern that HEADING_KEYWORDS_RE needs to match.
        if use_heuristics:
            heur_anchors = find_heuristic_anchors(xhtml_root)
            anchors = [a[0] for a in heur_anchors]
        else:
            doc_anchors_info = anchor_map.get(rel_html_path, [])
            anchors = [info[0] for info in doc_anchors_info if info[0]]
        
        merge_consecutive_paragraphs(xhtml_root)
        

        if anchors:
            roots = split_xhtml_by_anchors(xhtml_root, anchors)
            spine_index = list(spine_node).index(itemref)
            spine_node.remove(itemref)
            manifest_node.remove(item_el)
            
            doc_split_map = {}
            for j, root in enumerate(roots):
                new_href_name = f"{Path(href).stem}_sec_{j}.xhtml"
                new_href = str((Path(href).parent / new_href_name).as_posix())
                if new_href.startswith("./"):
                    new_href = new_href[2:]
                new_id = f"{idref}_sec_{j}"
                
                new_file_path = opf_dir / new_href
                new_file_path.write_bytes(serialize_xhtml(root, content))
                
                if j == 0:
                    doc_split_map[""] = new_href
                else:
                    anchor_id = anchors[j-1]
                    doc_split_map[anchor_id] = new_href
                    
                new_item = ET.Element(
                    "{http://www.idpf.org/2007/opf}item",
                    attrib={
                        "id": new_id,
                        "href": new_href,
                        "media-type": "application/xhtml+xml"
                    }
                )
                manifest_node.append(new_item)
                
                new_itemref = ET.Element(
                    "{http://www.idpf.org/2007/opf}itemref",
                    attrib={"idref": new_id}
                )
                spine_node.insert(spine_index + j, new_itemref)
                
            split_map[rel_html_path] = doc_split_map
            
            try:
                html_path.unlink()
            except Exception:
                pass
        else:
            html_path.write_bytes(serialize_xhtml(xhtml_root, content))
            
    if split_map:
        update_nav_ncx(workspace_dir, opf_dir, split_map)

    if use_heuristics:
        # Collect final list of spine sections in order to rebuild the TOC
        new_toc_entries = []
        final_manifest = {}
        for item in manifest_node.findall(".//{*}item"):
            item_id = item.attrib.get("id", "")
            href_val = item.attrib.get("href", "")
            if item_id and href_val:
                final_manifest[item_id] = href_val

        for itemref in spine_node.findall(".//{*}itemref"):
            idref = itemref.attrib.get("idref", "")
            href_val = final_manifest.get(idref)
            if not href_val:
                continue

            item_el = manifest_node.find(f".//{{*}}item[@id='{idref}']")
            if item_el is not None and item_el.attrib.get("media-type") != "application/xhtml+xml":
                continue

            html_file_path = opf_dir / href_val
            if not html_file_path.exists():
                continue

            try:
                html_bytes = html_file_path.read_bytes()
                xhtml_root_final = ET.fromstring(
                    replace_html_entities(html_bytes.decode("utf-8", errors="ignore")).encode("utf-8")
                )
                title = _find_element_title(xhtml_root_final, default_title=idref)
                new_toc_entries.append((href_val, title))
            except Exception:
                new_toc_entries.append((href_val, idref))

        if new_toc_entries:
            # Rebuild the NAV file if it exists
            if nav_href:
                nav_path = opf_dir / nav_href
                if nav_path.exists():
                    regenerate_nav_file(nav_path, new_toc_entries, opf_dir)

            # Rebuild the NCX file if it exists
            ncx_href = None
            for item in manifest_node.findall(".//{*}item"):
                if item.attrib.get("media-type") == "application/x-dtbncx+xml":
                    ncx_href = item.attrib.get("href")
                    break
            if ncx_href:
                ncx_path = opf_dir / ncx_href
                if ncx_path.exists():
                    regenerate_ncx_file(ncx_path, new_toc_entries, opf_dir)
        
    opf_path.write_bytes(serialize_opf(opf_root))


# --- Preprocessor Implementation ---

class EPUBPreprocessor(BasePreprocessor):
    """Anchor-aware EPUB parser with paragraph line-wrap merging."""
    
    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".epub"
        
    def extract_sections(self, file_path: Path) -> List[DocumentSection]:
        from epuboverlay.pipeline import parse_epub_toc, replace_html_entities
        
        results: List[DocumentSection] = []
        with zipfile.ZipFile(file_path, "r") as zf:
            container_xml = zf.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is None:
                raise ValueError("EPUB container is missing a rootfile entry")
                
            opf_path = rootfile.attrib.get("full-path", "")
            opf_root = ET.fromstring(zf.read(opf_path))
            opf_dir = Path(opf_path).parent
            
            toc_map = parse_epub_toc(zf, opf_path, opf_root)
            
            manifest: Dict[str, str] = {}
            for item in opf_root.findall(".//{*}manifest/{*}item"):
                item_id = item.attrib.get("id", "")
                href = item.attrib.get("href", "")
                if item_id and href:
                    manifest[item_id] = href
                    
            anchor_map: Dict[str, List[Tuple[str, str]]] = {}
            
            nav_href = None
            for item in opf_root.findall(".//{*}manifest/{*}item"):
                if "nav" in item.attrib.get("properties", "").split():
                    nav_href = item.attrib.get("href")
                    break
                    
            def _normalize(base: Path, hr: str) -> str:
                combined = (base / hr).as_posix()
                return os.path.normpath(combined).replace("\\", "/").lstrip("./").lstrip("/")
                
            if nav_href:
                try:
                    nav_zip_path = _normalize(opf_dir, nav_href)
                    nav_content = zf.read(nav_zip_path)
                    nav_root = ET.fromstring(nav_content)
                    nav_dir = Path(nav_zip_path).parent
                    
                    for a_el in nav_root.findall(".//{*}a"):
                        href = a_el.attrib.get("href", "").strip()
                        if href:
                            clean_href = href.split("#")[0]
                            anchor = href.split("#")[1] if "#" in href else ""
                            resolved_href = _normalize(nav_dir, clean_href)
                            title = "".join(a_el.itertext()).strip()
                            if title:
                                anchor_map.setdefault(resolved_href, []).append((anchor, title))
                except Exception:
                    pass
            
            if not anchor_map:
                ncx_href = None
                for item in opf_root.findall(".//{*}manifest/{*}item"):
                    if item.attrib.get("media-type") == "application/x-dtbncx+xml":
                        ncx_href = item.attrib.get("href")
                        break
                if ncx_href:
                    try:
                        ncx_zip_path = _normalize(opf_dir, ncx_href)
                        ncx_content = zf.read(ncx_zip_path)
                        ncx_root = ET.fromstring(ncx_content)
                        ncx_dir = Path(ncx_zip_path).parent
                        
                        for nav_point in ncx_root.findall(".//{*}navPoint"):
                            content_el = nav_point.find("{*}content")
                            label_el = nav_point.find(".//{*}navLabel/{*}text")
                            if content_el is not None and label_el is not None:
                                src = content_el.attrib.get("src", "").strip()
                                text = (label_el.text or "").strip()
                                if src and text:
                                    clean_src = src.split("#")[0]
                                    anchor = src.split("#")[1] if "#" in src else ""
                                    resolved_src = _normalize(ncx_dir, clean_src)
                                    anchor_map.setdefault(resolved_src, []).append((anchor, text))
                    except Exception:
                        pass
            
            for itemref in opf_root.findall(".//{*}spine/{*}itemref"):
                idref = itemref.attrib.get("idref", "")
                href = manifest.get(idref)
                if not href:
                    continue
                
                item = opf_root.find(f".//{{*}}manifest/{{*}}item[@id='{idref}']")
                if item is not None and item.attrib.get("media-type") != "application/xhtml+xml":
                    continue
                    
                html_path = _normalize(opf_dir, href)
                if html_path not in zf.namelist():
                    continue
                    
                xhtml_bytes = zf.read(html_path)
                try:
                    xhtml_root = ET.fromstring(
                        replace_html_entities(
                            xhtml_bytes.decode("utf-8", errors="ignore")
                        ).encode("utf-8")
                    )
                except ET.ParseError:
                    continue
                
                # Detect heuristic headings BEFORE merging paragraphs
                use_heuristics = (len(anchor_map) <= 1)
                if use_heuristics:
                    heur_anchors = find_heuristic_anchors(xhtml_root)
                    anchors = [a[0] for a in heur_anchors]
                    doc_anchors_info = heur_anchors
                else:
                    doc_anchors_info = anchor_map.get(html_path, [])
                    anchors = [info[0] for info in doc_anchors_info if info[0]]
                
                merge_consecutive_paragraphs(xhtml_root)
                
                if anchors:
                    roots = split_xhtml_by_anchors(xhtml_root, anchors)
                    
                    for j, root in enumerate(roots):
                        if j == 0:
                            title = toc_map.get(html_path, "Introduction/Preface")
                        else:
                            anchor_id = anchors[j-1]
                            title = "Section"
                            for a, t in doc_anchors_info:
                                if a == anchor_id:
                                    title = t
                                    break
                                    
                        full_text = " ".join("".join(root.itertext()).strip().split())
                        if full_text:
                            sec_id = f"{idref}_sec_{j}"
                            results.append(DocumentSection(
                                id=sec_id,
                                title=title,
                                text_content=full_text,
                                char_count=len(full_text),
                                preview=full_text[:1000]
                            ))
                else:
                    title = toc_map.get(html_path)
                    if not title:
                        title_el = xhtml_root.find(".//{*}title")
                        heading_el = xhtml_root.find(".//{*}h1")
                        if heading_el is None:
                            heading_el = xhtml_root.find(".//{*}h2")
                        if heading_el is not None and heading_el.text:
                            title = heading_el.text.strip()
                        elif title_el is not None and title_el.text:
                            title = title_el.text.strip()
                        else:
                            title = idref
                            
                    full_text = " ".join("".join(xhtml_root.itertext()).strip().split())
                    if full_text:
                        results.append(DocumentSection(
                            id=idref,
                            title=title,
                            text_content=full_text,
                            char_count=len(full_text),
                            preview=full_text[:1000]
                        ))
                        
        return results
