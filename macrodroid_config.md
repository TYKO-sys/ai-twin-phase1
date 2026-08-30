# MacroDroid Automation Config (Free Alternative to Tasker)
# ============================================================
# MacroDroid is free on Google Play with a generous free tier.
#
# Install: https://play.google.com/store/apps/details?id=com.arlosoft.macrodroid
#
# This file describes THREE macros to set up manually.
# Each takes ~2 minutes.
#
# ============================================================
# CRITICAL: THE URL FORMAT
# ============================================================
#
# The URL MUST include the word "bot" between api.telegram.org/
# and your bot token. This is the #1 mistake people make.
#
# CORRECT:
#   https://api.telegram.org/bot<TOKEN>/sendMessage
#
# WRONG (will silently fail):
#   https://api.telegram.org/<TOKEN>/sendMessage
#
# Example CORRECT url (fake token):
#   https://api.telegram.org/bot8958071104:AAHdYGbHN-7UTMwBwjPJY/sendMessage
#
# Notice the "bot" right after the slash, before the numbers.
#
# ============================================================
# HOW TO VERIFY YOUR URL WORKS
# ============================================================
#
# Before setting up MacroDroid, test your URL in a browser:
#
# 1. Open Chrome or any browser on your phone
# 2. Paste this URL (replace <TOKEN> and <CHAT_ID>):
#    https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=/morning
# 3. Press Enter
# 4. You should see a JSON response like:
#    {"ok":true,"result":{"message_id":123,...}}
# 5. Check Telegram — your bot should have sent "/morning" to you
#
# If step 4 shows "ok":false or an error, your URL is wrong.
# Fix it before proceeding to MacroDroid.
#
# ============================================================


## Macro 1: Morning Ping (9:00 AM daily)

**Trigger:**
- Type: Date/Time Trigger
- Days: Every day
- Time: 09:00

**Actions (in order):**
1. HTTP Request
   - Request method: POST
   - URL: `https://api.telegram.org/botYOUR_TOKEN_HERE/sendMessage`
     (Replace YOUR_TOKEN_HERE with your actual bot token.
      DO NOT forget the "bot" prefix after the slash!)
   - Content type: `application/x-www-form-urlencoded`
   - Content Body (as form params):
     - `chat_id` = `YOUR_TELEGRAM_USER_ID`
     - `text` = `/morning`

**Constraints:**
- (none)


## Macro 2: Evening Ping (9:00 PM daily)

**Trigger:**
- Type: Date/Time Trigger
- Days: Every day
- Time: 21:00

**Actions (in order):**
1. HTTP Request
   - Request method: POST
   - URL: `https://api.telegram.org/botYOUR_TOKEN_HERE/sendMessage`
   - Content type: `application/x-www-form-urlencoded`
   - Content Body (as form params):
     - `chat_id` = `YOUR_TELEGRAM_USER_ID`
     - `text` = `/evening`

**Constraints:**
- (none)


## Macro 3: Weekly Review (Sunday 8:00 PM)

**Trigger:**
- Type: Date/Time Trigger
- Days: Sunday only
- Time: 20:00

**Actions (in order):**
1. HTTP Request
   - Request method: POST
   - URL: `https://api.telegram.org/botYOUR_TOKEN_HERE/sendMessage`
   - Content type: `application/x-www-form-urlencoded`
   - Content Body (as form params):
     - `chat_id` = `YOUR_TELEGRAM_USER_ID`
     - `text` = `/weekly`

**Constraints:**
- (none)


## ============================================================
## ALTERNATIVE (SIMPLER): Use Query Params instead of Content Body
## ============================================================
#
# If MacroDroid's Content Body editor is confusing, you can put
# everything in the URL as query params instead. This is simpler.
#
# For each macro, set:
#   - Request method: GET (or POST, both work)
#   - URL (all on one line):
#
#   https://api.telegram.org/botYOUR_TOKEN_HERE/sendMessage?chat_id=YOUR_CHAT_ID&text=/morning
#
# (Replace /evening or /weekly as needed for each macro.)
#
# No Content Body needed. No Query Params tab needed.
# Everything is in the URL.
#
# ============================================================


## ============================================================
## HOW TO TEST
## ============================================================
#
# 1. In MacroDroid, tap your macro
# 2. Tap "Test Action" (NOT "Test Trigger")
# 3. Wait 5 seconds
# 4. Check Telegram — your bot should have sent the message
#
# If nothing appears:
#   - Open MacroDroid → your macro → tap the HTTP Request action
#   - Tap "Test Action" again
#   - Look for a response code at the bottom of the screen
#   - 200 = success
#   - 401 = wrong token
#   - 400 = wrong chat_id or missing params
#   - 404 = URL is wrong (probably missing "bot" prefix)
#
# ============================================================


## ============================================================
## TROUBLESHOOTING: "Test Action does nothing"
## ============================================================
#
# 1. Check the URL has "bot" after the slash:
#      ✓ https://api.telegram.org/bot<TOKEN>/sendMessage
#      ✗ https://api.telegram.org/<TOKEN>/sendMessage
#
# 2. Test the URL in a browser first (see above)
#
# 3. Make sure chat_id is your NUMERIC user ID (from @userinfobot),
#    not your username
#
# 4. Make sure the token has no spaces or line breaks in it
#
# 5. If using Content Body: make sure Content Type is set to
#    "application/x-www-form-urlencoded" and params are entered
#    as key-value pairs, not as a raw string
#
# 6. If using Query Params tab instead of URL: make sure each param
#    is on its own line with the value in the "Value" column
#
# ============================================================
