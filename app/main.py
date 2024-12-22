from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx
from collections import defaultdict
from typing import Optional
from datetime import datetime
from cachetools import TTLCache
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Force reload environment variables
load_dotenv(override=True)

class Settings(BaseSettings):
    FLIGHT_API_KEY: str
    API_BASE_URL: str = "https://api.flightapi.io"
    CACHE_TTL: int = 300
    CACHE_MAXSIZE: int = 100
    RATE_LIMIT: str = "30/minute"
    
    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings(_env_file='.env', _env_file_encoding='utf-8')

flights_cache = TTLCache(maxsize=settings.CACHE_MAXSIZE, ttl=settings.CACHE_TTL)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
@limiter.limit(settings.RATE_LIMIT)
async def home(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "error": error}
    )

@app.post("/flights")
@limiter.limit(settings.RATE_LIMIT)
async def get_flights(request: Request, airport_code: str = Form(...)):
    if len(airport_code) != 3:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Please enter a valid 3-letter airport code"}
        )
    
    airport_code = airport_code.upper()
    cache_key = f"flights_{airport_code}"
    
    if cache_key in flights_cache:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "flights": flights_cache[cache_key],
                "airport_code": airport_code
            }
        )
    
    try:
        transport = httpx.AsyncHTTPTransport(retries=3)
        async with httpx.AsyncClient(
            timeout=60.0,  # Increased to 60 seconds
            transport=transport
        ) as client:
            response = await client.get(
                f"{settings.API_BASE_URL}/compschedule/{settings.FLIGHT_API_KEY}",
                params={
                    'mode': 'arrivals',
                    'day': '1',
                    'iata': airport_code.lower()
                }
            )
            
            # Check response status
            response.raise_for_status()
            
            data = response.json()
            country_flights = defaultdict(int)
            
            if isinstance(data, list):
                for item in data:
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
            
            flight_data = sorted(
                country_flights.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            flights_cache[cache_key] = flight_data
            
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "flights": flight_data,
                    "airport_code": airport_code
                }
            )
            
    except httpx.TimeoutException:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Request timed out after 60 seconds. The airport might have too many flights to process. Please try again or try a different airport."}
        )
    except httpx.HTTPStatusError as e:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"API Error: {e.response.status_code} - {e.response.text}"}
        )
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"An unexpected error occurred: {str(e)}"}
        )

@app.get("/health")
@limiter.limit(settings.RATE_LIMIT)
async def health_check(request: Request):
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "cache_size": len(flights_cache),
        "cache_info": {
            "current_size": flights_cache.currsize,
            "maxsize": flights_cache.maxsize,
            "ttl": flights_cache.ttl
        },
        "rate_limit": settings.RATE_LIMIT
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 