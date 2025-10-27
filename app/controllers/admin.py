import os
from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import Literal
import io
import csv

from app.services import data_extractor_service

router = APIRouter()
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

def verify_admin_key(x_api_key: str = Header(...)):
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Admin API Key")


class ExtractionRequest(BaseModel):
    location: str
    extraction_type: Literal["restaurants", "attractions"]
    max_results: int = 40


@router.get("/admin", response_class=HTMLResponse)
async def get_admin_dashboard():
    # This HTML is updated with a new "Download CSV" button
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>InTra Admin Dashboard</title>
        <style>
            body { font-family: sans-serif; background: #f0f2f5; color: #333; margin: 40px; }
            .container { max-width: 600px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h1, h2 { color: #1d4ed8; }
            label { display: block; margin-top: 15px; font-weight: bold; }
            input, select { width: 100%; padding: 8px; margin-top: 5px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
            button { background: #1d4ed8; color: white; padding: 10px 15px; border: none; border-radius: 4px; margin-top: 20px; cursor: pointer; font-size: 16px; }
            button.secondary { background: #34d399; margin-left: 10px; }
            button:disabled { background: #999; }
            #status { margin-top: 20px; padding: 10px; background: #e2e8f0; border-radius: 4px; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>InTra Data Extractor</h1>
            <label for="apiKey">Admin API Key:</label>
            <input type="password" id="apiKey" value="your-secret-admin-key">

            <label for="location">Location (e.g., Chiang Mai):</label>
            <input type="text" id="location" value="Chiang Mai">

            <label for="type">Data Type:</label>
            <select id="type">
                <option value="restaurants">Restaurants</option>
                <option value="attractions">Tourist Attractions</option>
            </select>

            <label for="maxResults">Max Results:</label>
            <input type="number" id="maxResults" value="40">

            <button id="saveBtn" onclick="startJob()">Save to Database</button>
            <button id="csvBtn" class="secondary" onclick="downloadCsv()">Download CSV</button>

            <div id="status">Status: Idle.</div>
        </div>

        <script>
            function getFormValues() {
                return {
                    apiKey: document.getElementById('apiKey').value,
                    location: document.getElementById('location').value,
                    extraction_type: document.getElementById('type').value,
                    max_results: parseInt(document.getElementById('maxResults').value, 10),
                };
            }

            async function startJob() {
                const { apiKey, ...payload } = getFormValues();
                const statusDiv = document.getElementById('status');
                document.getElementById('saveBtn').disabled = true;
                document.getElementById('csvBtn').disabled = true;
                statusDiv.textContent = `Starting job to save ${payload.max_results} ${payload.extraction_type} from ${payload.location} to the database... This may take several minutes.`;

                try {
                    const response = await fetch('/api/admin/start-extraction', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
                        body: JSON.stringify(payload)
                    });
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.detail);
                    statusDiv.textContent = 'Success! Job started on the server. Check logs for progress.';
                } catch (error) {
                    statusDiv.textContent = 'Error: ' + error.message;
                } finally {
                    document.getElementById('saveBtn').disabled = false;
                    document.getElementById('csvBtn').disabled = false;
                }
            }

            async function downloadCsv() {
                const { apiKey, ...payload } = getFormValues();
                const statusDiv = document.getElementById('status');
                document.getElementById('saveBtn').disabled = true;
                document.getElementById('csvBtn').disabled = true;
                statusDiv.textContent = `Fetching data to generate CSV files... This may take a moment.`;

                try {
                    const placesPromise = fetch('/api/admin/export-csv?file_type=places', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
                        body: JSON.stringify(payload)
                    });
                    const reviewsPromise = fetch('/api/admin/export-csv?file_type=reviews', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
                        body: JSON.stringify(payload)
                    });

                    const [placesResponse, reviewsResponse] = await Promise.all([placesPromise, reviewsPromise]);

                    if (!placesResponse.ok || !reviewsResponse.ok) throw new Error('Failed to fetch data for CSV.');

                    const placesBlob = await placesResponse.blob();
                    const reviewsBlob = await reviewsResponse.blob();

                    const downloadLink = (blob, filename) => {
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        window.URL.revokeObjectURL(url);
                        document.body.removeChild(a);
                    };

                    downloadLink(placesBlob, `${payload.extraction_type}.csv`);
                    await new Promise(r => setTimeout(r, 200)); // Small delay
                    downloadLink(reviewsBlob, `${payload.extraction_type}_reviews.csv`);

                    statusDiv.textContent = 'Success! CSV files are downloading.';
                } catch (error) {
                    statusDiv.textContent = 'Error: ' + error.message;
                } finally {
                    document.getElementById('saveBtn').disabled = false;
                    document.getElementById('csvBtn').disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.post("/admin/start-extraction", dependencies=[Depends(verify_admin_key)])
async def start_extraction_endpoint(request: ExtractionRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(
        data_extractor_service.run_extraction_job,
        request.extraction_type,
        request.location,
        request.max_results
    )
    return {"message": "Extraction job has been successfully started in the background."}


# --- NEW CSV EXPORT ENDPOINT ---
@router.post("/admin/export-csv", dependencies=[Depends(verify_admin_key)])
async def export_csv_endpoint(request: ExtractionRequest, file_type: Literal["places", "reviews"]):
    """
    Fetches data on-demand and returns it directly as a downloadable CSV file.
    """
    places_data, reviews_data = await data_extractor_service.fetch_and_format_data(
        request.extraction_type,
        request.location,
        request.max_results
    )

    output = io.StringIO()
    writer = None

    if file_type == "places" and places_data:
        headers = places_data[0].keys()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(places_data)
        filename = f"{request.extraction_type}.csv"
    elif file_type == "reviews" and reviews_data:
        headers = reviews_data[0].keys()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(reviews_data)
        filename = f"{request.extraction_type}_reviews.csv"
    else:
        output.write("No data found for the selected criteria.")
        filename = "empty.txt"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )