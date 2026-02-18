#!/usr/bin/env python3
"""Génère le PDF de réponse au mail de Justine Pogeant (ESIEE)."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Image
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "export_base_données", "Reponse_Questions_BDD_Medialise.pdf")

# ── Couleurs ──
BLUE = HexColor("#2B579A")
LIGHT_BLUE = HexColor("#E8EEF7")
GREEN = HexColor("#1A7F37")
GRAY = HexColor("#666666")
LIGHT_GRAY = HexColor("#F5F5F5")
DARK = HexColor("#222222")
ORANGE = HexColor("#E67E22")

def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT,
        pagesize=A4,
        leftMargin=2.2*cm,
        rightMargin=2.2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=22, textColor=BLUE, spaceAfter=6,
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=11, textColor=GRAY, alignment=TA_CENTER,
        spaceAfter=20,
    )
    heading_style = ParagraphStyle(
        'QHeading', parent=styles['Heading2'],
        fontSize=13, textColor=BLUE, spaceBefore=18, spaceAfter=8,
        borderWidth=0, leftIndent=0,
    )
    question_style = ParagraphStyle(
        'Question', parent=styles['Normal'],
        fontSize=10, textColor=DARK, backColor=LIGHT_BLUE,
        borderPadding=(8, 8, 8, 8), spaceBefore=6, spaceAfter=10,
        leftIndent=10, rightIndent=10, leading=14,
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontSize=10.5, textColor=DARK, leading=15,
        spaceAfter=6, alignment=TA_JUSTIFY,
    )
    bold_style = ParagraphStyle(
        'BoldBody', parent=body_style,
        fontName='Helvetica-Bold',
    )
    code_style = ParagraphStyle(
        'Code', parent=styles['Code'],
        fontSize=8.5, backColor=LIGHT_GRAY,
        borderPadding=(6, 6, 6, 6),
        leftIndent=15, rightIndent=15,
        spaceAfter=8, leading=12,
        fontName='Courier',
    )
    bullet_style = ParagraphStyle(
        'Bullet', parent=body_style,
        leftIndent=25, bulletIndent=12,
        spaceBefore=2, spaceAfter=2,
    )
    note_style = ParagraphStyle(
        'Note', parent=body_style,
        fontSize=9.5, textColor=HexColor("#555555"),
        leftIndent=15, borderColor=ORANGE,
        borderWidth=1, borderPadding=(6,6,6,10),
        backColor=HexColor("#FFF8F0"),
    )

    story = []

    # ═══════════════════════════════════════
    # EN-TÊTE
    # ═══════════════════════════════════════
    story.append(Paragraph("MEDIALISE", title_style))
    story.append(Paragraph("Réponse aux questions sur la base de données", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE))
    story.append(Spacer(1, 8))

    # Contexte
    meta_style = ParagraphStyle('Meta', parent=body_style, fontSize=9.5, textColor=GRAY)
    story.append(Paragraph("<b>De :</b> Équipe Medialise — SAE BUT3", meta_style))
    story.append(Paragraph("<b>À :</b> Justine Pogeant — ESIEE", meta_style))
    story.append(Paragraph("<b>Objet :</b> Réponses à vos questions sur la structure de la BDD Medialise", meta_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph(
        "Bonsoir Justine,", body_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Merci pour vos questions, c'est tout à fait normal de les poser vu la taille de la base. "
        "On va répondre point par point de manière simple.", body_style))
    story.append(Spacer(1, 8))

    # ═══════════════════════════════════════
    # QUESTION 1
    # ═══════════════════════════════════════
    story.append(Paragraph("Question 1 — Lien entre substances et medicines", heading_style))

    story.append(Paragraph(
        "<i>« Comment les tables substances et medicines sont-elles liées exactement ? "
        "Lequel sert réellement de clé de référence ? »</i>",
        question_style))

    story.append(Paragraph(
        "En fait, on a <b>2 versions</b> de ces tables dans la base (l'ancienne v1 et la nouvelle v3). "
        "La v3 est la version actuelle, c'est celle que vous devez utiliser.", body_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Version actuelle : medicines_v3 + substances_v3</b>", bold_style))
    story.append(Spacer(1, 2))

    story.append(Paragraph(
        "Le lien se fait comme ça : chaque document dans <b>medicines_v3</b> a un champ "
        "<font face='Courier' color='#2B579A'>substance_ref_ids</font> qui est un <b>tableau d'ObjectId</b>. "
        "Ces ObjectId pointent directement vers les <font face='Courier' color='#2B579A'>_id</font> "
        "des documents dans <b>substances_v3</b>.", body_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph("Concrètement, ça donne :", body_style))

    story.append(Paragraph(
        '<font face="Courier">'
        '// Dans medicines_v3 :<br/>'
        '{<br/>'
        '&nbsp;&nbsp;"_id": ObjectId("abc123..."),<br/>'
        '&nbsp;&nbsp;"medicine_key": "medicine:paracetamol",<br/>'
        '&nbsp;&nbsp;"inns": ["PARACETAMOL"],<br/>'
        '&nbsp;&nbsp;"substance_ref_ids": [ObjectId("def456...")],&nbsp;&nbsp;← clé de lien<br/>'
        '&nbsp;&nbsp;"substance_labels": ["PARACETAMOL"],<br/>'
        '&nbsp;&nbsp;"countries": ["FR", "US"]<br/>'
        '}<br/><br/>'
        '// Dans substances_v3 :<br/>'
        '{<br/>'
        '&nbsp;&nbsp;"_id": ObjectId("def456..."),&nbsp;&nbsp;← c\'est cet _id qui est référencé<br/>'
        '&nbsp;&nbsp;"label": "PARACETAMOL",<br/>'
        '&nbsp;&nbsp;"sources": { "pubchem": {...}, "drugbank": {...} }<br/>'
        '}'
        '</font>',
        code_style))

    story.append(Paragraph(
        "💡 <b>En résumé</b> : la clé de référence c'est <font face='Courier' color='#2B579A'>_id</font> "
        "de <b>substances_v3</b>, et elle est stockée dans le champ "
        "<font face='Courier' color='#2B579A'>substance_ref_ids</font> de <b>medicines_v3</b>. "
        "C'est un lien <b>1 médicament → N substances</b> (un médicament peut avoir plusieurs principes actifs).",
        note_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Il y a aussi un 3ème niveau : <b>medicine_market</b>. C'est la table des produits commercialisés "
        "(les marques qu'on trouve en pharmacie). Chaque entrée dans medicine_market a un champ "
        "<font face='Courier' color='#2B579A'>medicine_ref</font> qui pointe vers le "
        "<font face='Courier' color='#2B579A'>_id</font> de medicines_v3.", body_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph(
        '<font face="Courier">'
        'substance_v3 &nbsp;←──&nbsp; medicines_v3 &nbsp;←──&nbsp; medicine_market<br/>'
        '(principe actif)&nbsp;&nbsp;&nbsp;(médicament)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(marque commerciale)<br/><br/>'
        'Exemple :<br/>'
        'PARACETAMOL &nbsp;&nbsp;←── &nbsp;paracetamol 500mg &nbsp;←──&nbsp; DOLIPRANE 500mg (FR, Sanofi)'
        '</font>',
        code_style))

    # ═══════════════════════════════════════
    # QUESTION 2
    # ═══════════════════════════════════════
    story.append(Paragraph("Question 2 — Les tables PharmGKB (pharmgkb_drugs & pharmgkb_relationships)", heading_style))

    story.append(Paragraph(
        "<i>« À quoi correspond le champ id dans pharmgkb_drugs et pharmgkb_relationships ? "
        "S'agit-il d'un identifiant propre ou d'une clé étrangère ? "
        "Quel est l'autre identifiant utilisé dans la relation ? »</i>",
        question_style))

    story.append(Paragraph(
        "Les tables PharmGKB viennent d'une source externe : <b>PharmGKB</b> "
        "(Pharmacogenomics Knowledge Base). C'est une base de données scientifique qui étudie "
        "comment les <b>gènes influencent la réponse aux médicaments</b>.",
        body_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Table pharmgkb_drugs</b>", bold_style))

    story.append(Paragraph(
        "Chaque document a un champ <font face='Courier' color='#2B579A'>_id</font> (ObjectId MongoDB classique) "
        "ET un champ <font face='Courier' color='#2B579A'>pharmgkb_id</font> qui est "
        "l'identifiant <b>propre à PharmGKB</b> (format : <font face='Courier'>PA449983</font>). "
        "C'est un identifiant unique qui vient directement de leur base.", body_style))

    story.append(Paragraph(
        '<font face="Courier">'
        '// pharmgkb_drugs :<br/>'
        '{<br/>'
        '&nbsp;&nbsp;"_id": ObjectId("..."),&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← ID MongoDB interne<br/>'
        '&nbsp;&nbsp;"pharmgkb_id": "PA449983", ← ID propre à PharmGKB<br/>'
        '&nbsp;&nbsp;"name": "paracetamol",<br/>'
        '&nbsp;&nbsp;"generic_names": ["acetaminophen"],<br/>'
        '&nbsp;&nbsp;"trade_names": ["Doliprane", "Tylenol"],<br/>'
        '&nbsp;&nbsp;"cross_references": { "drugbank": "DB00316", "pubchem": "1983" }<br/>'
        '}'
        '</font>',
        code_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>Table pharmgkb_relationships</b>", bold_style))

    story.append(Paragraph(
        "Cette table contient les <b>relations entre médicaments et gènes</b>. "
        "Elle utilise <b>deux identifiants PharmGKB</b> pour faire le lien :",
        body_style))

    story.append(Paragraph(
        '<font face="Courier">'
        '// pharmgkb_relationships :<br/>'
        '{<br/>'
        '&nbsp;&nbsp;"_id": ObjectId("..."),<br/>'
        '&nbsp;&nbsp;"entity1_id": "PA449983",&nbsp;&nbsp;&nbsp;← ID PharmGKB du médicament<br/>'
        '&nbsp;&nbsp;"entity1_name": "paracetamol",<br/>'
        '&nbsp;&nbsp;"entity1_type": "Chemical",<br/>'
        '&nbsp;&nbsp;"entity2_id": "PA128",&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← ID PharmGKB du gène<br/>'
        '&nbsp;&nbsp;"entity2_name": "CYP2E1",<br/>'
        '&nbsp;&nbsp;"entity2_type": "Gene",<br/>'
        '&nbsp;&nbsp;"evidence": "PGx Pathway",<br/>'
        '&nbsp;&nbsp;"pmid": "12345678"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← référence PubMed<br/>'
        '}'
        '</font>',
        code_style))

    story.append(Paragraph(
        "💡 <b>En résumé</b> : le <font face='Courier' color='#2B579A'>pharmgkb_id</font> est un identifiant "
        "<b>propre à PharmGKB</b> (pas une clé étrangère vers nos tables). "
        "Le lien entre pharmgkb_drugs et pharmgkb_relationships se fait via "
        "<font face='Courier' color='#2B579A'>entity1_id</font> (le médicament) et "
        "<font face='Courier' color='#2B579A'>entity2_id</font> (le gène). "
        "Les deux sont des PharmGKB IDs.",
        note_style))

    # ═══════════════════════════════════════
    # QUESTION 3
    # ═══════════════════════════════════════
    story.append(Paragraph("Question 3 — Le lien avec PubChem", heading_style))

    story.append(Paragraph(
        "<i>« Quel champ permet de faire le lien avec PubChem ? »</i>",
        question_style))

    story.append(Paragraph(
        "Le lien avec PubChem se fait dans la table <b>substances_v3</b>, à l'intérieur du champ "
        "<font face='Courier' color='#2B579A'>sources.pubchem</font>. "
        "Le champ clé c'est le <font face='Courier' color='#2B579A'>cid</font> "
        "(Compound ID, l'identifiant unique PubChem).", body_style))

    story.append(Paragraph(
        '<font face="Courier">'
        '// Dans substances_v3 :<br/>'
        '{<br/>'
        '&nbsp;&nbsp;"label": "PARACETAMOL",<br/>'
        '&nbsp;&nbsp;"sources": {<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;"pubchem": {<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"cid": 1983,&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← L\'ID PubChem (le lien !)<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"summary": {<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"molecular_formula": "C8H9NO2",<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"molecular_weight": 151.16,<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"canonical_smiles": "CC(=O)NC1=CC=C(O)C=C1"<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;}<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;},<br/>'
        '&nbsp;&nbsp;&nbsp;&nbsp;"drugbank": { "drugbank_id": "DB00316", ... }<br/>'
        '&nbsp;&nbsp;}<br/>'
        '}'
        '</font>',
        code_style))

    story.append(Paragraph(
        "Avec ce <font face='Courier' color='#2B579A'>cid</font>, on peut accéder à la page PubChem directement : "
        "<font color='#2B579A'>https://pubchem.ncbi.nlm.nih.gov/compound/1983</font>", body_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Il y a aussi une table <b>pubchem_compound_sections</b> (~115 000 documents) "
        "qui stocke les données détaillées PubChem. Le lien se fait aussi via le "
        "<font face='Courier' color='#2B579A'>cid</font>.",
        body_style))

    story.append(Paragraph(
        "💡 <b>En résumé</b> : le champ <font face='Courier' color='#2B579A'>sources.pubchem.cid</font> "
        "dans <b>substances_v3</b> est la clé qui fait le lien avec PubChem. "
        "Pareil pour DrugBank via <font face='Courier' color='#2B579A'>sources.drugbank.drugbank_id</font>.",
        note_style))

    # ═══════════════════════════════════════
    # QUESTION 4
    # ═══════════════════════════════════════
    story.append(Paragraph("Question 4 — Identifiants français vs anglais", heading_style))

    story.append(Paragraph(
        "<i>« Les identifiants en français et en anglais sont-ils distincts "
        "ou correspondent-ils au même enregistrement ? »</i>",
        question_style))

    story.append(Paragraph(
        "C'est une bonne question ! En fait <b>ce sont des enregistrements différents</b> "
        "dans <b>medicine_market</b>, mais ils pointent vers le <b>même médicament</b> dans medicines_v3.",
        body_style))

    story.append(Paragraph(
        "Explication : le champ <font face='Courier' color='#2B579A'>country</font> dans medicine_market "
        "indique le pays d'origine. Un médicament français (country = \"FR\") et un médicament "
        "américain (country = \"US\") auront des entrées séparées dans medicine_market, parce que "
        "les noms de marque, les dosages et les autorisations sont différents d'un pays à l'autre. "
        "Mais les deux peuvent pointer vers le <b>même _id dans medicines_v3</b> s'ils ont la même "
        "substance active.",
        body_style))

    story.append(Paragraph(
        '<font face="Courier">'
        '// Deux entrées medicine_market différentes :<br/><br/>'
        '{ "_id": "market:FR:DOLIPRANE 1000MG",&nbsp;&nbsp;← produit français<br/>'
        '&nbsp;&nbsp;"country": "FR",<br/>'
        '&nbsp;&nbsp;"brand_title": "DOLIPRANE 1000 mg",<br/>'
        '&nbsp;&nbsp;"medicine_ref": ObjectId("abc123...") }&nbsp;&nbsp;← même médicament<br/><br/>'
        '{ "_id": "market:US:TYLENOL 1000MG",&nbsp;&nbsp;&nbsp;&nbsp;← produit américain<br/>'
        '&nbsp;&nbsp;"country": "US",<br/>'
        '&nbsp;&nbsp;"brand_title": "TYLENOL Extra Strength",<br/>'
        '&nbsp;&nbsp;"medicine_ref": ObjectId("abc123...") }&nbsp;&nbsp;← même médicament !'
        '</font>',
        code_style))

    story.append(Paragraph(
        "💡 <b>En résumé</b> : dans <b>medicine_market</b>, les entrées FR et US sont distinctes "
        "(noms de marque, dosages, RCP différents). Mais dans <b>medicines_v3</b>, c'est le même "
        "enregistrement car c'est le même principe actif. Et dans <b>substances_v3</b>, "
        "c'est évidemment la même substance.",
        note_style))

    # ═══════════════════════════════════════
    # SCHÉMA RÉCAP
    # ═══════════════════════════════════════
    story.append(Spacer(1, 12))
    story.append(Paragraph("Schéma récapitulatif des liens", heading_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BLUE))
    story.append(Spacer(1, 6))

    story.append(Paragraph(
        '<font face="Courier" size="8.5">'
        '┌─────────────────────────────────────────────────────────────────────────┐<br/>'
        '│                     ARCHITECTURE DES DONNÉES V3                        │<br/>'
        '├─────────────────────────────────────────────────────────────────────────┤<br/>'
        '│                                                                        │<br/>'
        '│  substances_v3                                                         │<br/>'
        '│  ├─ _id: ObjectId &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← CLÉ PRINCIPALE                      │<br/>'
        '│  ├─ label: "PARACETAMOL"                                               │<br/>'
        '│  └─ sources:                                                           │<br/>'
        '│  &nbsp;&nbsp;&nbsp;├─ pubchem.cid &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← lien PubChem                       │<br/>'
        '│  &nbsp;&nbsp;&nbsp;└─ drugbank.drugbank_id &nbsp;← lien DrugBank                     │<br/>'
        '│  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;▲                                              │<br/>'
        '│  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│ substance_ref_ids                          │<br/>'
        '│                  │                                                     │<br/>'
        '│  medicines_v3    │                                                     │<br/>'
        '│  ├─ _id: ObjectId│ &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← CLÉ PRINCIPALE                      │<br/>'
        '│  ├─ substance_ref_ids: [ObjectId] &nbsp;← LIEN vers substances_v3     │<br/>'
        '│  └─ inns, countries                                                    │<br/>'
        '│  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;▲                                              │<br/>'
        '│  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;│ medicine_ref                               │<br/>'
        '│                  │                                                     │<br/>'
        '│  medicine_market  │                                                    │<br/>'
        '│  ├─ _id: "market:FR:DOLIPRANE" &nbsp;&nbsp;&nbsp;← CLÉ COMPOSITE              │<br/>'
        '│  ├─ medicine_ref: ObjectId &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;← LIEN vers medicines_v3       │<br/>'
        '│  ├─ country: "FR"                                                      │<br/>'
        '│  └─ brand_title, rcp, ...                                              │<br/>'
        '│                                                                        │<br/>'
        '│  pharmgkb_drugs &nbsp;&nbsp;&nbsp;&nbsp;pharmgkb_relationships                      │<br/>'
        '│  ├─ pharmgkb_id ←────── entity1_id (médicament)                       │<br/>'
        '│  └─ name &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;entity2_id (gène)                        │<br/>'
        '│                                                                        │<br/>'
        '└─────────────────────────────────────────────────────────────────────────┘'
        '</font>',
        code_style))

    # ═══════════════════════════════════════
    # CONCLUSION
    # ═══════════════════════════════════════
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=1, color=BLUE))
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        "N'hésitez pas si vous avez d'autres questions, on est disponibles pour vous aider ! "
        "Si un truc n'est pas clair dans les données, envoyez-nous un exemple "
        "et on vous expliquera.",
        body_style))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Bon courage pour la suite !", body_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Cordialement,", body_style))
    story.append(Paragraph("<b>Adel — Équipe Medialise</b>", body_style))
    story.append(Paragraph("<i>SAE BUT3 Informatique</i>", ParagraphStyle(
        'SignItalic', parent=body_style, fontSize=9.5, textColor=GRAY)))

    # Build
    doc.build(story)
    print(f"PDF genere : {OUTPUT}")

if __name__ == "__main__":
    build_pdf()
