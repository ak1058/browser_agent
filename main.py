import os
import asyncio
import sys

import asyncio
import platform



from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv
import asyncio
from playwright.async_api import async_playwright
import logging
import json
import re
import base64



load_dotenv()

app = FastAPI(
    title="Browser Automation API",
    description="API for natural language browser automation",
    version="1.0.0"
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print(os.getenv("OPENAI_API_KEY", "https://api.openai.com/v1"))

client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    api_key=os.getenv("OPENAI_API_KEY")
)

class CommandRequest(BaseModel):
    command: str
    url: Optional[str] = None
    max_steps: Optional[int] = 5
    credentials: Optional[dict] = None

class AutomationResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
    screenshot: Optional[str] = None


async def interpret_command(natural_language: str) -> dict:
    """Convert natural language to automation script with proper JSON parsing"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """
                You are a browser automation expert. Convert the user's natural language command into a JSON structure.
                The JSON should include the starting URL if not provided and have an "actions" array with these possible action types:

                - navigate: {url: string} (REQUIRED as first action if no URL provided)
                - click: {selector: string}
                - fill: {selector: string, text: string} (text will be provided later)
                - press: {selector: string, key: string}
                - wait: {timeout: number}
                - scroll: {direction: "up"|"down", pixels: number}
                - login: {username_selector: string, password_selector: string, submit_selector: string}
                - search: {query: string, search_selector: string, submit_selector: string}
                - like_post: {index: number} (likes the nth post in the feed)
                - comment_post: {index: number, text: string} (comments on the nth post)
                - share_post: {index: number} (shares the nth post)
                
                Example input: "Login to LinkedIn and search for playwright jobs"
                Example output: {
                    "starting_url": "https://linkedin.com",
                    "actions": [
                        {"type": "click", "selector": "a[data-tracking-control-name='guest_homepage-basic_nav-header-signin']"},
                        {"type": "fill", "selector": "input[name='session_key']", "text": "YOUR_USERNAME"},
                        {"type": "fill", "selector": "input[name='session_password']", "text": "YOUR_PASSWORD"},
                        {"type": "click", "selector": "button[type='submit']"},
                        {"type": "wait", "timeout": 3000},
                        {"type": "fill", "selector": "input[role='combobox']", "text": "playwright jobs"},
                        {"type": "press", "selector": "input[role='combobox']", "key": "Enter"},
                        {"type": "like_post", "index": 1}
                    ]
                }
                 
                IMPORTANT: 
                 1. Never include actual credentials in the response
                2. Every action must have a "type" field as the first key
                """},
                {"role": "user", "content": natural_language}
            ],
            temperature=0.3,
            response_format={ "type": "json_object" },
            max_tokens=1000
        )
        
        response_content = response.choices[0].message.content
        json_str = re.sub(r'```json|```', '', response_content).strip()
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to parse command response")
    except Exception as e:
        logger.error(f"Command interpretation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Command interpretation failed")

async def execute_actions(actions: list, starting_url: str = None) -> AutomationResponse:
    """Execute browser automation actions"""
    async with async_playwright() as p:
       
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "--start-maximized"
            ],
            timeout=60000  
        )
        
        
        context = await browser.new_context(
            viewport={'width': 1366, 'height': 768},
            locale='en-US'
        )
        
        
        page = await context.new_page()
        
        try:
           
            if starting_url:
                logger.info(f"Navigating to starting URL: {starting_url}")
                try:
                    await page.goto(
                        starting_url,
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception as e:
                    logger.error(f"Navigation failed: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to navigate to starting URL: {str(e)}"
                    )

            results = {"steps": []}

            for action in actions:
                step_result = {"action": action, "success": True}
                
                try:
                    action_type = action["type"]
                    logger.info(f"Executing action: {action_type}")

                    if action_type == "navigate":
                        await page.goto(action["url"], wait_until="networkidle")
                    
                    elif action_type == "click":
                        await page.wait_for_selector(action["selector"], state="visible", timeout=10000)
                        await page.click(action["selector"])
                    
                    elif action_type == "fill":
                        selector = action["selector"]
                        await page.wait_for_selector(selector, state="visible", timeout=10000)
                        await page.fill(selector, action["text"])
                    
                    elif action_type == "press":
                        if "selector" not in action:
                            raise Exception("Press action requires a selector parameter")
                        await page.wait_for_selector(action["selector"], state="visible", timeout=10000)
                        await page.press(action["selector"], action["key"])
                    
                    elif action_type == "wait":
                        await page.wait_for_timeout(action["timeout"])
                    
                    elif action_type == "scroll":
                        await page.evaluate(f"window.scrollBy(0, {action['pixels']})")
                    
                    elif action_type == "login":
                        
                        await page.wait_for_selector(action["username_selector"], state="visible", timeout=10000)
                        await page.fill(action["username_selector"], action["username"])
                        
                        
                        await page.wait_for_selector(action["password_selector"], state="visible", timeout=10000)
                        await page.fill(action["password_selector"], action["password"])
                        
                       
                        await page.wait_for_selector(action["submit_selector"], state="visible", timeout=10000)
                        await page.click(action["submit_selector"])
                    
                    elif action_type == "search":
                        await page.wait_for_selector(action["search_selector"], state="visible", timeout=10000)
                        await page.fill(action["search_selector"], action["query"])
                        await page.click(action["submit_selector"])

                    elif action_type == "like_post":
                        try:
                            logger.info("Starting like_post action...")
                            
                           
                            logger.info("Waiting for feed content...")
                            await page.wait_for_selector(".scaffold-finite-scroll__content", timeout=15000)
                            logger.info("Feed content loaded successfully")
                            
                            
                            logger.info("Locating posts...")
                            posts = await page.query_selector_all("[data-id^='urn:li:activity']")
                            logger.info(f"Found {len(posts)} posts")
                            
                            if not posts:
                                logger.error("No posts found on page")
                                raise Exception("No posts found - may need different selectors")

                            post_index = min(action.get("index", 1) - 1, len(posts) - 1)
                            logger.info(f"Selecting post at index {post_index + 1}")
                            
                            post = posts[post_index]
                            logger.info("Scrolling post into view...")
                            await post.scroll_into_view_if_needed()
                            await page.wait_for_timeout(2000)

                           
                            logger.info("Locating like button...")
                            like_button = await post.query_selector(
                                "button.react-button__trigger[aria-label^='React'], "
                                "button.social-actions-button, "
                                "button[aria-label*='Like']"
                            )
                            
                            if not like_button:
                                logger.warning("Primary selectors failed, trying fallbacks...")
                                like_button = await post.query_selector(
                                    "button:has(svg[data-icon*='thumb']), "
                                    "button:has(img[alt='like'])"
                                )
                                if not like_button:
                                    logger.error("All like button selectors failed")
                                    raise Exception("Like button not found")

                          
                            current_state = {
                                "aria_pressed": await like_button.get_attribute("aria-pressed") or "null",
                                "aria_label": await like_button.get_attribute("aria-label") or "null",
                                "classes": await like_button.get_attribute("class") or "null"
                            }
                            print(f"DEBUG - CURRENT BUTTON STATE: {current_state}")  
                            logger.info(f"CURRENT BUTTON STATE: {current_state}")  
                            
                            
                            logger.info("Attempting to click like button...")
                            await like_button.evaluate("btn => { btn.click(); console.log('Like button clicked via JS') }")
                            await page.wait_for_timeout(3000)

                            
                            new_state = {
                                "aria_pressed": await like_button.get_attribute("aria-pressed") or "null",
                                "aria_label": await like_button.get_attribute("aria-label") or "null",
                                "classes": await like_button.get_attribute("class") or "null"
                            }
                            print(f"DEBUG - NEW BUTTON STATE: {new_state}")  
                            logger.info(f"NEW BUTTON STATE: {new_state}")

                            
                            if (new_state["aria_pressed"] == current_state["aria_pressed"] or 
                                new_state["aria_label"] == current_state["aria_label"]):
                                logger.error(f"State didn't change! Before: {current_state}, After: {new_state}")
                                raise Exception("Like action didn't register - button state unchanged")

                            logger.info("Like action successful!")
                            return {
                                "success": True,
                                "message": "Successfully liked post",
                                "debug": {
                                    "before": current_state,
                                    "after": new_state
                                }
                            }

                        except Exception as e:
                            logger.error(f"Like failed: {str(e)}", exc_info=True)
                            return {
                                "success": False,
                                "message": str(e),
                                "debug": {
                                    "error": str(e),
                                    "screenshot": base64.b64encode(await page.screenshot()).decode() if 'page' in locals() else None
                                }
                            }

                    
                    await page.wait_for_timeout(1000)
                    
                except Exception as e:
                    step_result["success"] = False
                    step_result["error"] = str(e)
                    logger.error(f"Action failed: {action} - {str(e)}")
                    
                    try:
                        screenshot_bytes = await page.screenshot(type="png")
                        step_result["screenshot"] = base64.b64encode(screenshot_bytes).decode("utf-8")
                    except:
                        pass

                results["steps"].append(step_result)

            
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

            return AutomationResponse(
                success=True,
                message="Automation completed",
                data=results,
                screenshot=f"data:image/png;base64,{screenshot_b64}"
            )
            
        except Exception as e:
            logger.error(f"Automation failed: {str(e)}")
            
            try:
                screenshot_bytes = await page.screenshot(type="png")
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                return AutomationResponse(
                    success=False,
                    message=f"Automation failed: {str(e)}",
                    screenshot=f"data:image/png;base64,{screenshot_b64}"
                )
            except:
                return AutomationResponse(
                    success=False,
                    message=f"Automation failed: {str(e)}"
                )
        finally:
            
            await asyncio.sleep(1)
            await context.close()
            await browser.close()

@app.post("/interact", response_model=AutomationResponse)
async def interact(request: CommandRequest):
    """Main endpoint for natural language browser automation"""
    try:
        actions_data = await interpret_command(request.command)
        logger.info(f"Interpreted actions: {actions_data}")
        
        if not isinstance(actions_data, dict) or "actions" not in actions_data:
            raise HTTPException(status_code=400, detail="Invalid actions format")
            
        
        starting_url = request.url if request.url else actions_data.get("starting_url")
        
        
        if request.credentials:
            for action in actions_data["actions"]:
                if action["type"] == "fill":
                
                    if "text" in action and action["text"] == "YOUR_USERNAME":
                        action["text"] = request.credentials.get("username", "")
                  
                    elif "password" in action["selector"].lower() or ("text" in action and action["text"] == "YOUR_PASSWORD"):
                        action["text"] = request.credentials.get("password", "")
                elif action["type"] == "login" and "username_selector" in action:
                   
                    action["username"] = request.credentials.get("username", "")
                    action["password"] = request.credentials.get("password", "")
        
        return await execute_actions(actions_data["actions"], starting_url)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))