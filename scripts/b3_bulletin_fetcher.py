# scripts/b3_bulletin_fetcher.py
# Sourced from: https://github.com/renanikeda/options-pricing/blob/main/data/B3_options.py
# Fetches B3 official daily bulletins and parses negotiation + product XML data.

import requests
import zipfile
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Literal
import os
from time import sleep
import shutil


def parse_xml(xml_path: str):
    try:
        tree = ET.parse(xml_path)
        return tree.getroot()
    except (ET.ParseError, IOError) as e:
        print(f"Error parsing XML: {e}")
        return None


def parse_products_xml_to_df(xml_path: str) -> pd.DataFrame:
    root = parse_xml(xml_path)
    if root is None:
        return pd.DataFrame()
    ns = {
        "bvmf052": "urn:bvmf.052.01.xsd",
        "head": "urn:iso:std:iso:20022:tech:xsd:head.001.001.01",
        "bvmf100": "urn:bvmf.100.02.xsd",
    }
    rows = []
    for pricrpt in root.findall(".//bvmf100:Instrm", ns):
        record = {}
        record["Ticker"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:TckrSymb", namespaces=ns
        )
        if not record["Ticker"]:
            continue
        record["Ação"] = pricrpt.findtext(
            "bvmf100:FinInstrmAttrCmon/bvmf100:Asst", namespaces=ns
        )
        record["ID_ação"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:UndrlygInstrmId/bvmf100:OthrId/bvmf100:Id",
            namespaces=ns,
        )
        record["Style"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:OptnStyle", namespaces=ns
        )
        record["Type"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:OptnTp", namespaces=ns
        )
        record["Strike"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:ExrcPric", namespaces=ns
        )
        record["Maturity"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:XprtnDt", namespaces=ns
        )
        record["Descrição"] = pricrpt.findtext(
            "bvmf100:FinInstrmAttrCmon/bvmf100:Desc", namespaces=ns
        )
        rows.append(record)
    return pd.DataFrame(rows)


def parse_negotiation_xml_to_df(xml_path: str) -> pd.DataFrame:
    root = parse_xml(xml_path)
    if root is None:
        return pd.DataFrame()
    ns = {
        "bvmf052": "urn:bvmf.052.01.xsd",
        "head": "urn:iso:std:iso:20022:tech:xsd:head.001.001.01",
        "bvmf217": "urn:bvmf.217.01.xsd",
    }
    rows = []
    for pricrpt in root.findall(".//bvmf217:PricRpt", ns):
        record = {}
        record["ID"] = pricrpt.findtext(
            "bvmf217:FinInstrmId/bvmf217:OthrId/bvmf217:Id", namespaces=ns
        )
        record["TradeDate"] = pricrpt.findtext(
            "bvmf217:TradDt/bvmf217:Dt", namespaces=ns
        )
        record["Ticker"] = pricrpt.findtext(
            "bvmf217:SctyId/bvmf217:TckrSymb", namespaces=ns
        )
        record["FirstPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:FrstPric", namespaces=ns
        )
        if not record["FirstPrice"]:
            continue
        record["MinPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:MinPric", namespaces=ns
        )
        record["MaxPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:MaxPric", namespaces=ns
        )
        record["LastPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:LastPric", namespaces=ns
        )
        record["AvgPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:TradAvrgPric", namespaces=ns
        )
        record["TradeQty"] = pricrpt.findtext(
            "bvmf217:TradDtls/bvmf217:TradQty", namespaces=ns
        )
        rows.append(record)
    return pd.DataFrame(rows)


def download_and_save_zipfile(file_code: str, save_path: str = None) -> str | None:
    headers = {
        "referer": (
            "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/"
            "market-data/historico/boletins-diarios/pesquisa-por-pregao/"
            "pesquisa-por-pregao/"
        ),
    }
    url = f"https://www.b3.com.br/pesquisapregao/download?filelist={file_code}.zip,"
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        if save_path is None:
            save_path = f"{file_code}.zip"
        elif os.path.isdir(save_path):
            save_path = os.path.join(save_path, f"{file_code}.zip")
        os.makedirs(
            os.path.dirname(save_path) if os.path.dirname(save_path) else ".",
            exist_ok=True,
        )
        with open(save_path, "wb") as f:
            f.write(response.content)
        return save_path
    except Exception as e:
        print(f"Error downloading {file_code}: {e}")
        return None


def unzip_file(zip_path: str, extract_to: str = None, remove_zip: bool = True):
    try:
        if extract_to is None:
            extract_to = os.path.dirname(zip_path) or "."
        extracted_files = []
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
            for filename in zip_ref.namelist():
                extracted_path = os.path.join(extract_to, filename)
                if ".zip" in extracted_path:
                    nested = unzip_file(
                        extracted_path,
                        "/".join(extracted_path.split("/")[:-1]),
                    )
                    if isinstance(nested, list):
                        extracted_files.extend(nested)
                    else:
                        extracted_files.append(nested)
                else:
                    extracted_files.append(extracted_path)
        if remove_zip:
            os.remove(zip_path)
        return extracted_files
    except zipfile.BadZipFile:
        raise
    except IOError as e:
        print(f"Error extracting: {e}")
        return None


def get_b3_daily(
    date_str: str,
    output_dir: str = "/tmp/b3_bulletins",
    type: Literal["negotiation", "product"] = "negotiation",
    retries: int = 0,
) -> pd.DataFrame:
    """
    Fetch B3 daily bulletin for a given date (format: YYYYMMDD).
    type='negotiation' returns traded prices; type='product' returns contract specs.
    """
    try:
        prefix = "PR" if type == "negotiation" else "IN"
        code = prefix + date_str[2:]  # e.g. 20200316 → PR200316
        os.makedirs(output_dir, exist_ok=True)
        zip_path = download_and_save_zipfile(code, output_dir)
        if not zip_path:
            return pd.DataFrame()
        extracted = unzip_file(zip_path, os.path.join(output_dir, code))
        if not extracted:
            return pd.DataFrame()
        xml_file = next((f for f in extracted if f.endswith(".xml")), None)
        if not xml_file:
            return pd.DataFrame()
        if type == "negotiation":
            df = parse_negotiation_xml_to_df(xml_file)
        else:
            df = parse_products_xml_to_df(xml_file)
        # cleanup
        shutil.rmtree(os.path.join(output_dir, code), ignore_errors=True)
        return df
    except zipfile.BadZipFile:
        if retries >= 3:
            return pd.DataFrame()
        sleep(0.5 * (retries + 1))
        return get_b3_daily(date_str, output_dir, type, retries + 1)
    except Exception as e:
        print(f"Error for {date_str}: {e}")
        return pd.DataFrame()
