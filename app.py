import re

import smtplib

import json
from datetime import datetime, timezone

from supabase import create_client

from email.mime.text import MIMEText

import streamlit as st

from google import genai

from google.genai import types

from prompts import (

    SUMMARY_REQUEST_PROMPT,

    SYSTEM_PROMPT,

    WELCOME_MESSAGE_TEMPLATE,

)

# -------------------- CONFIGURATION --------------------

MODEL_NAME = "gemini-3.8-flash"
EXTRACTION_MODEL_NAMES = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]

st.set_page_config(

    page_title="MacroSnap",

    page_icon="🥗",

    layout="centered",

)

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

GMAIL_ADDRESS = st.secrets["GMAIL_ADDRESS"]

GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"].replace(" ", "")

SUPABASE_URL = st.secrets["SUPABASE_URL"]

SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

def get_supabase_client():

    if "supabase_client" not in st.session_state:

        st.session_state.supabase_client = create_client(

            SUPABASE_URL,

            SUPABASE_KEY,

        )

    return st.session_state.supabase_client

# -------------------- GEMINI CLIENT --------------------

@st.cache_resource

def get_gemini_client():

    return genai.Client(api_key=GEMINI_API_KEY)

gemini_client = get_gemini_client()

def start_chat():

    return gemini_client.chats.create(

        model=MODEL_NAME,

        config=types.GenerateContentConfig(

            system_instruction=SYSTEM_PROMPT

        ),

    )

def ask_gemini(parts):

    try:

        response = st.session_state.chat.send_message(parts)

        return response.text or "Sorry, I couldn't generate a response."

    except Exception as error:

        st.error(f"Gemini error: {error}")

        return None

def extract_and_save_meal(parts):
    """Extract nutrition data from a meal and save it to Supabase."""
    try:
        prompt = """
        Analyze the food described or shown in the supplied content.
        Return only valid JSON with these fields:
        {
            "meal_name": "short name of the meal",
            "calories": 0,
            "protein": 0,
            "carbs": 0,
            "fat": 0
        }
        Estimate the total for the visible or described portion.
        Calories are kcal; protein, carbs and fat are grams.
        Use reasonable estimates and non-negative numbers.
        If no actual meal or food can be identified, return:
        {"meal_name": "", "calories": 0, "protein": 0,
         "carbs": 0, "fat": 0}
        """

        # Try the current stable lightweight model first, then fall back to Flash
        # if the first model is temporarily unavailable.
        response = None
        model_errors = []
        for extraction_model in EXTRACTION_MODEL_NAMES:
            try:
                response = gemini_client.models.generate_content(
                    model=extraction_model,
                    contents=[*parts, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )
                break
            except Exception as model_error:
                model_errors.append(f"{extraction_model}: {model_error}")

        if response is None:
            raise RuntimeError(
                "Nutrition extraction failed with all configured models. "
                + " | ".join(model_errors)
            )

        nutrition = json.loads(response.text or "{}")
        meal_name = str(nutrition.get("meal_name", "")).strip()
        calories = float(nutrition.get("calories", 0))
        protein = float(nutrition.get("protein", 0))
        carbs = float(nutrition.get("carbs", 0))
        fat = float(nutrition.get("fat", 0))
        values = [calories, protein, carbs, fat]

        if not meal_name or calories <= 0:
            return False

        import math
        if any(
            not math.isfinite(value) or value < 0 or value > 100000
            for value in values
        ):
            return False

        user_id = st.session_state.get("user_id")
        if not user_id:
            return False

        # Supply eaten_at explicitly in case the database column has no default.
        result = get_supabase_client().table("meals").insert({
            "user_id": user_id,
            "meal_name": meal_name,
            "calories": calories,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "eaten_at": datetime.now(timezone.utc).isoformat(),
        }).select("id, meal_name").execute()

        if not result.data:
            return False

        return True

    except Exception:
        # Temporarily keep meal-storage/extraction failures out of the UI.
        # The chat response still displays; a success message appears only if saved.
        return False

# -------------------- EMAIL --------------------

def send_email(to_address, user_name, summary):

    try:

        message = MIMEText(

            f"Hi {user_name},\n\n"

            "Here is your MacroSnap meal summary:\n\n"

            f"{summary}\n\n"

            "Note: Nutrition values are estimates and may vary "

            "depending on portion size and ingredients.",

            "plain",

            "utf-8",

        )

        message["Subject"] = "Your MacroSnap Meal Summary"

        message["From"] = GMAIL_ADDRESS

        message["To"] = to_address

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:

            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)

            server.send_message(message)

        return True, "Email sent successfully!"

    except Exception as error:

        return False, str(error)

# -------------------- CHAT DISPLAY --------------------

def render_message(message):

    with st.chat_message(message["role"]):

        if message["kind"] == "text":

            st.write(message["content"])

        elif message["kind"] == "image":

            st.image(message["content"], width="stretch")

def add_message(role, kind, content):

    message = {

        "role": role,

        "kind": kind,

        "content": content,

    }

    st.session_state.messages.append(message)

    render_message(message)

# -------------------- AUTHENTICATION --------------------

if "authenticated" not in st.session_state:

    st.session_state.authenticated = False

def finish_login(user, email):

    user_metadata = getattr(user, "user_metadata", {}) or {}

    st.session_state.authenticated = True

    st.session_state.user_id = str(user.id)

    st.session_state.email = email

    st.session_state.name = (

        user_metadata.get("full_name")

        or email.split("@")[0]

    )

    st.session_state.chat = start_chat()

    st.session_state.messages = []

    st.session_state.onboarded = True

if not st.session_state.authenticated:

    st.title("🥗 MacroSnap")

    st.caption("Your personal AI nutrition companion")

    auth_mode = st.radio(

        "Welcome",

        ["Log in", "Create account"],

        horizontal=True,

    )

    with st.form("auth_form"):

        name = ""

        if auth_mode == "Create account":

            name = st.text_input("Your name")

        email = st.text_input(

            "Email address",

            placeholder="you@example.com",

        )

        password = st.text_input(

            "Password",

            type="password",

            help="Use at least 8 characters.",

        )

        submitted = st.form_submit_button(

            "Log in" if auth_mode == "Log in"

            else "Create account",

            width="stretch",

        )

    if submitted:

        email = email.strip().lower()

        client = get_supabase_client()

        if not email or not password:

            st.warning("Please enter your email and password.")

        elif auth_mode == "Create account" and not name.strip():

            st.warning("Please enter your name.")

        elif auth_mode == "Create account" and len(password) < 8:

            st.warning("Please use a password of at least 8 characters.")

        else:

            try:

                with st.spinner("Authenticating..."):

                    if auth_mode == "Create account":

                        result = client.auth.sign_up({

                            "email": email,

                            "password": password,

                            "options": {

                                "data": {

                                    "full_name": name.strip()

                                }

                            },

                        })

                        if result.session and result.user:

                            finish_login(result.user, email)

                            st.rerun()

                        else:

                            st.success(

                                "Account created! Check your email "

                                "for the confirmation link. After "

                                "confirming, return here and log in."

                            )

                    else:

                        result = client.auth.sign_in_with_password({

                            "email": email,

                            "password": password,

                        })

                        if result.session and result.user:

                            finish_login(result.user, email)

                            st.rerun()

                        else:

                            st.error(

                                "Login did not return an authenticated "

                                "session. Please try again."

                            )

            except Exception as error:

                st.error(f"Authentication failed: {error}")

    st.stop()

# -------------------- LOGOUT --------------------

with st.sidebar:

    st.caption(f"Signed in as {st.session_state.email}")

    if st.button("Log out", width="stretch"):

        try:

            get_supabase_client().auth.sign_out()

        except Exception as error:

            st.error(f"Could not sign out: {error}")

        else:

            for key in [

                "authenticated",

                "user_id",

                "email",

                "name",

                "chat",

                "messages",

                "onboarded",

            ]:

                st.session_state.pop(key, None)

            st.rerun()

# -------------------- HEADER --------------------

header_col, button_col = st.columns(

    [5, 2],

    vertical_alignment="center",

)

with header_col:

    st.title("🥗 MacroSnap")

with button_col:

    send_disabled = len(st.session_state.messages) < 2

    email_clicked = st.button(

        "📧 Send Email",

        disabled=send_disabled,

        width="stretch",

    )

st.caption(

    f"Logged in as {st.session_state.name} | "

    f"Summaries go to {st.session_state.email}"

)

# -------------------- EMAIL SUMMARY --------------------

if email_clicked:

    with st.spinner("Preparing your meal summary..."):

        summary = ask_gemini([SUMMARY_REQUEST_PROMPT])

    if summary:

        with st.spinner("Sending email..."):

            success, info = send_email(

                st.session_state.email,

                st.session_state.name,

                summary,

            )

        if success:

            st.success(info)

        else:

            st.error(f"Could not send email: {info}")

# -------------------- CHAT HISTORY --------------------

if not st.session_state.messages:

    add_message(

        "assistant",

        "text",

        WELCOME_MESSAGE_TEMPLATE.format(

            name=st.session_state.name

        ),

    )

else:

    for message in st.session_state.messages:

        render_message(message)

# -------------------- TEXT AND PHOTO UPLOAD --------------------

st.divider()

st.subheader("💬 Ask MacroSnap")

st.caption(

    "Type a food question, attach a meal photo, "

    "or use your camera below."

)

user_input = st.chat_input(

    "What are you eating?",

    accept_file=True,

    file_type=["jpg", "jpeg", "png"],

)

if user_input:

    photo = user_input.files[0] if user_input.files else None

    text = user_input.text.strip() if user_input.text else ""

    parts = []

    if photo is not None:

        photo_bytes = photo.getvalue()

        add_message("user", "image", photo_bytes)

        parts.append(

            types.Part.from_bytes(

                data=photo_bytes,

                mime_type=photo.type,

            )

        )

    if text:

        add_message("user", "text", text)

        parts.append(text)

    elif photo is not None:

        parts.append(

            "Identify this meal and estimate its calories, "

            "protein, carbohydrates and fat. Mention uncertainty "

            "because the portion size may not be clear."

        )

    if parts:

        with st.spinner("Analyzing your meal..."):

            answer = ask_gemini(parts)

        if answer:

            add_message("assistant", "text", answer)
            if extract_and_save_meal(parts):
                st.success("Meal nutrition saved to your account!")

# -------------------- COMPACT CAMERA BUTTON --------------------

if "show_camera" not in st.session_state:

    st.session_state.show_camera = False

camera_col, help_col = st.columns([1, 4])

with camera_col:

    camera_clicked = st.button(

        "📸 Scan Meal" if not st.session_state.show_camera

        else "✖ Close",

        key="toggle_camera",

        width="stretch",

    )

if camera_clicked:

    st.session_state.show_camera = not st.session_state.show_camera

if st.session_state.show_camera:

    st.divider()

    st.subheader("📸 Capture Your Meal")

    camera_photo = st.camera_input("Take a picture")

    if camera_photo is not None:

        camera_question = st.text_input(

            "What would you like to know?",

            placeholder="e.g. Estimate calories and protein",

            key="camera_question",

        )

        if st.button("🔍 Analyze Photo", key="analyze_camera"):

            question = camera_question.strip() or (

                "Identify this meal and estimate its calories, "

                "protein, carbohydrates and fat."

            )

            photo_bytes = camera_photo.getvalue()

            add_message("user", "image", photo_bytes)

            add_message("user", "text", question)

            parts = [

                types.Part.from_bytes(

                    data=photo_bytes,

                    mime_type=camera_photo.type,

                ),

                question,

            ]

            with st.spinner("Analyzing your meal..."):

                answer = ask_gemini(parts)

            if answer:

                add_message("assistant", "text", answer)
                if extract_and_save_meal(parts):
                    st.success("Meal nutrition saved to your account!")
