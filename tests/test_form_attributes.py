"""Managed form attributes must not hold Массив/Структура/Соответствие.

Regression for v1.3.16: БуферСтрокПротокола as form requisite broke form open.
v1.3.19: Перем Массив/Структура also broken for managed form procedures —
use ТекстПротокола / temp storage address (Строка) instead.
"""

from __future__ import annotations

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM_XML = ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form.xml"
MODULE_BSL = ROOT / "ПрисоединениеЖурналаРегистрации" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"

ASSIGN_RE = re.compile(
    r"^\s*(?P<name>[А-Яа-яA-Za-z_][А-Яа-яA-Za-z0-9_]*)\s*=\s*Новый\s+(?P<typ>Массив|Структура|Соответствие)\b",
    re.MULTILINE,
)
PEREM_RE = re.compile(r"(?m)^\s*Перем\s+")
STATE_IDENT_RE = re.compile(
    r"(?<![А-Яа-яA-Za-z0-9_])СостояниеПрисоединения(?![А-Яа-яA-Za-z0-9_])"
)


def form_attribute_names() -> set[str]:
    tree = ET.parse(FORM_XML)
    root = tree.getroot()
    names: set[str] = set()
    for attr in root.iter():
        if attr.tag == "Attribute" or attr.tag.endswith("}Attribute"):
            name = attr.get("name")
            if name:
                names.add(name)
    return names


def attributes_with_empty_type() -> list[str]:
    tree = ET.parse(FORM_XML)
    root = tree.getroot()
    empty: list[str] = []
    for attr in root.iter():
        if attr.tag != "Attribute" and not attr.tag.endswith("}Attribute"):
            continue
        name = attr.get("name")
        if not name:
            continue
        type_el = None
        for child in attr:
            if child.tag == "Type" or child.tag.endswith("}Type"):
                type_el = child
                break
        if type_el is None:
            empty.append(name)
            continue
        if len(type_el) == 0 and not (type_el.text and type_el.text.strip()):
            empty.append(name)
    return empty


def forbidden_assignments_to_form_attrs() -> list[str]:
    text = MODULE_BSL.read_text(encoding="utf-8-sig")
    attrs = form_attribute_names()
    issues: list[str] = []
    for m in ASSIGN_RE.finditer(text):
        name, typ = m.group("name"), m.group("typ")
        if name in attrs:
            line = text.count("\n", 0, m.start()) + 1
            issues.append(f"{name} = Новый {typ} (line {line}) assigned to form attribute")
    return issues


class TestFormAttributes(unittest.TestCase):
    def test_no_empty_type_attributes(self):
        empty = attributes_with_empty_type()
        self.assertEqual(
            empty,
            [],
            "Form attributes with empty <Type/> break managed forms: " + ", ".join(empty),
        )

    def test_no_forbidden_type_assignments_to_form_requisites(self):
        issues = forbidden_assignments_to_form_attrs()
        self.assertEqual(
            issues,
            [],
            "Assigning non-serializable values to form requisites:\n" + "\n".join(issues),
        )

    def test_no_session_state_as_form_requisite_or_module_var(self):
        attrs = form_attribute_names()
        text = MODULE_BSL.read_text(encoding="utf-8-sig")
        for name in ("БуферСтрокПротокола", "КэшДанныхАнализа"):
            self.assertNotIn(name, attrs, f"{name} must not be a form attribute")
            self.assertNotIn(name, text, f"{name} must not appear in Module.bsl")
        self.assertNotIn("СостояниеПрисоединения", attrs)
        self.assertIsNone(
            STATE_IDENT_RE.search(text),
            "СостояниеПрисоединения must not be used as variable/attribute",
        )
        self.assertFalse(PEREM_RE.search(text), "Module.bsl must not use Перем for session state")
        self.assertIn("АдресСостоянияПрисоединения", attrs)
        self.assertIn("АдресСостоянияПрисоединения", text)
        self.assertIn("ШагМастера", attrs)
        self.assertIn("ТекстШагаМастера", attrs)
        self.assertIn("ШагМастера", text)
        self.assertIn("ДедупликацияЗаписей", attrs)
        self.assertIn("РазбиватьИсточникПоДням", attrs)
        self.assertIn("ДедупликацияЗаписей", text)
        self.assertIn("РазбиватьИсточникПоДням", text)
        for cmd in (
            "ВосстановитьИзРезервнойКопии",
            "СохранитьПротокол",
            "МастерДалее",
            "МастерНазад",
        ):
            self.assertIn(cmd, text, f"handler {cmd} missing in Module.bsl")
            self.assertIn(f'name="{cmd}"', FORM_XML.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2).result.wasSuccessful() else 1)
