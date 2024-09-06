import requests
from bs4 import BeautifulSoup
import datetime
import pytz
import pandas as pd
import re
from google.cloud import bigquery
import logging

logging.basicConfig(level=logging.INFO)

CITIES = [
    "Berlin Hbf", "Hamburg Hbf", "Münich Hbf", "Köln Hbf", "Frankfurt(Main)Hbf",
    "Stuttgart Hbf", "Düsseldorf Hbf", "Leipzig Hbf", "Dortmund Hbf", "Essen Hbf",
    "Bremen Hbf", "Dresden Hbf", "Hannover Hbf", "Nürnberg Hbf", "Duisburg Hbf",
    "Bochum Hbf", "Wuppertal Hbf", "Bielefeld Hbf", "Bonn Hbf", "Münster(Westf)Hbf"
]


def get_train_data_for_city(city):
    logging.info(f"Starting to fetch train data for {city}.")
    # Obtener la hora actual en Europa Occidental
    tz = pytz.timezone('Europe/Berlin')
    current_time = datetime.datetime.now(tz)
    formatted_time = current_time.strftime("%H:00")

    url = "https://reiseauskunft.bahn.de/bin/bhftafel.exe/dn"
    params = {
        "country": "DE",
        "ld": "15082",
        "seqnr": "4",
        "protocol": "https:",
        "input": city,
        "ident": "fi.0865482.1497188234",
        "rt": "1",
        "productsFilter": "1111100000",
        "time": formatted_time,
        "date": current_time.strftime("%d.%m.%y"),
        "start": "1",
        "boardType": "arr",
        "rtMode": "DB-HYBRID"
    }
    response = requests.get(url, params=params)
    logging.info(f"Request URL for {city}: {response.url}")
    if response.status_code != 200:
        logging.error(
            f"Failed to fetch data for {city} at {formatted_time} on {current_time.strftime('%d.%m.%y')}. Status code: {response.status_code}")
        return pd.DataFrame()

    soup = BeautifulSoup(response.text, 'html.parser')

    data = []

    # Extraer información de cada fila de viaje para la hora actual
    for journey in soup.find_all("tr", id=lambda x: x and x.startswith("journeyRow_")):
        time = journey.find("td", class_="time").get_text(strip=True)
        expected_time_tag = journey.find("span", class_="delayOnTime bold")
        expected_time = expected_time_tag.get_text(
            strip=True) if expected_time_tag else time
        train_tags = journey.find_all("td", class_="train")
        train = "No train data available"
        for tag in train_tags:
            if tag.find("a") and tag.find("a").text.strip():
                train = tag.find("a").text.strip()
                break
        route = [span.get_text(strip=True)
                 for span in journey.find_all("span", class_="bold")]
        platform = journey.find("td", class_="platform").get_text(strip=True)
        ris_tag = journey.find("td", class_="ris")
        ris = ris_tag.get_text(strip=True) if ris_tag else ""
        link = journey.find("a", href=True)[
            'href'] if journey.find("a", href=True) else ""
        station_evaId = re.search(
            r"station_evaId=(\d+)", link).group(1) if "station_evaId" in link else "No station ID"

        # Determinar si hay atraso
        has_delay = 1 if ris and ris != time else 0

        # Añadir la fila de datos al listado
        data.append({
            "date": current_time.date(),
            "Hbf": city,
            "scheduled_time": time,
            "expected_time": expected_time,
            "train_model": train,
            "route": ', '.join(route),
            "platform": platform,
            "real_time_due_to_delay": ris,
            "has_delay": has_delay,
        })

    # Crear DataFrame con los datos recopilados
    df = pd.DataFrame(data)
    logging.info(f"Data fetching completed for {city}.")
    return df


def upload_to_bigquery(df):
    logging.info("Starting to upload data to BigQuery.")
    try:
        client = bigquery.Client()
        table_id = "tfmil3.datos_trenes.trenes_raw"

        job = client.load_table_from_dataframe(df, table_id)

        job.result()  # Wait for the job to complete
        logging.info(f"Loaded {job.output_rows} rows into {table_id}.")
    except Exception as e:
        logging.error(f"Failed to upload data to BigQuery: {e}")
        raise


def main(request):
    logging.info("Cloud Function triggered.")
    try:
        all_data = pd.DataFrame()
        for city in CITIES:
            city_data = get_train_data_for_city(city)
            all_data = pd.concat([all_data, city_data], ignore_index=True)

        if not all_data.empty:
            upload_to_bigquery(all_data)
            logging.info("Data has been uploaded to BigQuery.")
            return "Data has been uploaded to BigQuery."
        else:
            logging.warning("No data fetched for the current hour.")
            return "No data fetched for the current hour."
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return f"An error occurred: {e}"
