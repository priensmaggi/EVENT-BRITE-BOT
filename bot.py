import os
import sys
import json
import requests
import random
from datetime import datetime, timezone, timedelta

# ENV VARS FROM GITHUB SECRETS
EVENTBRITE_OAUTH_TOKEN = os.getenv("EVENTBRITE_OAUTH_TOKEN")
EVENTBRITE_ORGANIZER_ID = "110021953071"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
STATE_FILE = "state.json"

if not EVENTBRITE_OAUTH_TOKEN or not DISCORD_WEBHOOK_URL:
    print("Missing API Keys!")
    sys.exit(1)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                pass
    return {"all_events_state": {}, "last_morning_sweep": ""}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def send_discord_webhook(content, event=None):
    payload = {"content": content}
    
    if event:
        event_title = event.get("name", {}).get("text", "Untitled Event")
        event_url = event.get("url", f"https://www.eventbrite.com/e/{event.get('id')}")
        
        date_str = "Time TBD"
        if event.get("start", {}).get("local"):
            try:
                dt = datetime.fromisoformat(event["start"]["local"])
                date_str = dt.strftime("%A, %B %d, %Y, %I:%M %p")
            except:
                pass

        has_tickets = event.get("ticket_availability", {}).get("has_available_tickets", False)
        status_icon = "🟢 **Available**" if has_tickets else "⚪ **Unavailable / Closed**"
        
        embed = {
            "title": event_title,
            "url": event_url,
            "description": event.get("description", {}).get("text", "")[:500] if event.get("description") else "No description available.",
            "color": 15750455,
            "image": {"url": event.get("logo", {}).get("url", "")} if event.get("logo") else {},
            "fields": [
                {"name": "📅 Date & Time", "value": date_str, "inline": True},
                {"name": "🎟️ Ticket Status", "value": status_icon, "inline": True}
            ]
        }
        
        payload["content"] = f"{content}\n\n**{event_title}**\n📅 **When:** {date_str}\n🔗 **Link:** {event_url}"
        payload["embeds"] = [embed]
        
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"})
    except Exception as e:
        print("Webhook failed:", e)

def fetch_events():
    all_events = []
    page = 1
    has_more = True
    headers = {"Authorization": f"Bearer {EVENTBRITE_OAUTH_TOKEN}"}
    
    while has_more and page <= 5:
        url = f"https://www.eventbriteapi.com/v3/organizers/{EVENTBRITE_ORGANIZER_ID}/events/?status=live&order_by=start_desc&page={page}"
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            break
        data = res.json()
        all_events.extend(data.get("events", []))
        has_more = data.get("pagination", {}).get("has_more_items", False)
        page += 1
    return all_events

def run_bot():
    events = fetch_events()
    if not events:
        print("No events found.")
        return

    state = load_state()
    global_state = state.get("all_events_state", {})
    state_changed = False
    
    now = datetime.now(timezone.utc)
    # Convert to PHT (UTC+8)
    now_pht = now + timedelta(hours=8)
    today_date_str = now_pht.strftime("%Y-%m-%d")
    
    # 1. MORNING SWEEP LOGIC (Triggers around 8:00 AM PHT)
    # GitHub Actions cron may delay slightly, but it will fire when the hour is >= 8.
    last_sweep = state.get("last_morning_sweep", "")
    if last_sweep != today_date_str and now_pht.hour >= 8:
        any_tix = any(e.get("ticket_availability", {}).get("has_available_tickets", False) for e in events)
        
        no_tix_msgs = [
            "@everyone 🌅 **MAAYONG BUNTAG, MGA BAI!** 🌅\n\nJust woke up and did my morning sweep of Eventbrite. Currently, there are **ZERO tickets** available. Enjoy your coffee, keep your notifications on, and wait for the drop! ☕😎",
            "@everyone 🌅 **BANGON NA, MGA BAI!** 🌅\n\nMorning check complete! Eventbrite is completely empty right now. No tickets yet, but the Looksmaxxer is always watching. Have a great day ahead! 🍳🔥",
            "@everyone 🌅 **GOOD MORNING, MGA GWAPO OG GWAPA!** 🌅\n\nScanned the events and it’s a dry spell today—ZERO tickets available. Don't stress, just keep grinding and I'll ping you the second something drops! ☕💪"
        ]
        yes_tix_msgs = [
            "@everyone 🌅 **MAAYONG BUNTAG, MGA BAI!** 🌅\n\nWake up and get moving! I just did my morning sweep and there are **TICKETS AVAILABLE RIGHT NOW!** Go check Eventbrite before they sell out! ☕🚀",
            "@everyone 🌅 **BANGON NA, MGA BAI! ALERT!** 🌅\n\nNo time to sleep in! There are **LIVE TICKETS** on Eventbrite right now! Grab them before they're gone! 🍳🔥",
            "@everyone 🌅 **GOOD MORNING! EMERGENCY ALERT!** 🌅\n\nStart your day with a W! I just checked and there are **TICKETS AVAILABLE!** Go secure your spot right now! ☕🏃‍♂️💨"
        ]
        
        msg = random.choice(yes_tix_msgs if any_tix else no_tix_msgs)
        send_discord_webhook(msg)
        state["last_morning_sweep"] = today_date_str
        state_changed = True

    # 2. EVENT SCANNING LOGIC
    is_first_run = len(global_state) == 0

    for event in events:
        event_id = event["id"]
        has_tickets = event.get("ticket_availability", {}).get("has_available_tickets", False)
        
        if event_id not in global_state:
            # Brand new event
            if not is_first_run:
                content = "@everyone 🎉 **NEW EVENT + TICKETS AVAILABLE!** 🎉\n🗣️ **BISAYANG LOOKSMAXXER REMINDS YOU TO GET TICKETS FAST!**" if has_tickets else "@everyone 👀 **HEADS UP! NEW EVENT POSTED!** 👀\n🗣️ **BISAYANG LOOKSMAXXER SAYS WATCH THIS EVENT (NO TICKETS YET)**"
                send_discord_webhook(content, event)
            global_state[event_id] = has_tickets
            state_changed = True
        else:
            # Existing event
            if global_state[event_id] is False and has_tickets is True:
                send_discord_webhook("@everyone 🎟️ **TICKETS FREED UP FOR THIS EVENT!** 🎟️\n🗣️ **BISAYANG LOOKSMAXXER REMINDS YOU TO GET TICKETS FAST!**", event)
            
            if global_state[event_id] != has_tickets:
                global_state[event_id] = has_tickets
                state_changed = True

    if state_changed:
        state["all_events_state"] = global_state
        save_state(state)
        print("State updated and saved.")
    else:
        print("No changes. State identical.")

if __name__ == "__main__":
    run_bot()
