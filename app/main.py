from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import httpx
import os
from dotenv import load_dotenv
from collections import defaultdict
from typing import Optional
from datetime import datetime

# Force reload environment variables
load_dotenv(override=True)

API_BASE_URL = "https://api.flightapi.io"
API_KEY = os.getenv("FLIGHT_API_KEY")

print(f"Loaded API key: {API_KEY}")

if not API_KEY:
    raise ValueError("API key not found in environment variables")


if not API_KEY:
    raise ValueError("API_KEY not found in environment variables. Please check your .env file.")

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "error": error}
    )

@app.post("/flights")
async def get_flights(request: Request, airport_code: str = Form(...)):
    # Validate IATA code length
    if not airport_code or len(airport_code) != 3:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Please enter a valid 3-letter airport code"}
        )

    airport_code = airport_code.upper()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            api_url = f"{API_BASE_URL}/compschedule/{API_KEY}"
            params = {
                'mode': 'arrivals',
                'day': 1,
                'iata': airport_code.lower()
            }
            
            # Debug prints
            print(f"Making request to URL: {api_url}")
            print(f"With parameters: {params}")
            
            try:
                response = await client.get(api_url, params=params)
                print(f"Response status code: {response.status_code}")
            except Exception as request_error:
                print(f"Request error: {str(request_error)}")
                return templates.TemplateResponse(
                    "index.html",
                    {
                        "request": request,
                        "error": f"Failed to make API request: {str(request_error)}"
                    }
                )

            if response.status_code != 200:
                error_content = str(response.content.decode())
                print(f"Error response for {airport_code}: {error_content}")
                return templates.TemplateResponse(
                    "index.html",
                    {
                        "request": request,
                        "error": f"API request failed for {airport_code}: {error_content}"
                    }
                )

            data = response.json()
            
            # Process flights and count by country
            country_flights = defaultdict(int)
            
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                        
                    flights_data = (item.get('airport', {})
                                  .get('pluginData', {})
                                  .get('schedule', {})
                                  .get('arrivals', {})
                                  .get('data', []))
                    
                    for flight in flights_data:
                        country_name = (flight.get('flight', {})
                                      .get('airport', {})
                                      .get('origin', {})
                                      .get('position', {})
                                      .get('country', {})
                                      .get('name'))
                        
                        if country_name:
                            country_flights[country_name] += 1
            
            if not country_flights:
                return templates.TemplateResponse(
                    "index.html",
                    {
                        "request": request,
                        "error": f"No flight data found for airport code: {airport_code}"
                    }
                )

            print(f"Country flights: {country_flights}")
            flight_data = sorted(
                country_flights.items(),
                key=lambda x: x[1],
                reverse=True
            )

            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "flights": flight_data,
                    "airport_code": airport_code
                }
            )

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"An error occurred: {str(e)}"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 