import os
import json
import time
import sys
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify

tester_bp = Blueprint("tester", __name__, template_folder="templates", static_folder="static")

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")
CALLBACKS_FILE = os.path.join(os.path.dirname(__file__), "callbacks.json")
ORDER_COUNTER_FILE = os.path.join(os.path.dirname(__file__), "order_counter.txt")
CARDS_FILE = os.path.join(os.path.dirname(__file__), "cards.json")

def load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {
            "amount": 100,
            "shortDesc": "Короткое описание",
            "longDesc": "Описание по умолчанию",
            "backUrlSuccess": "https://tda-photo.ru/success",
            "backUrlFail": "https://tda-photo.ru/fail",
            "extraParam": "",
            "paymentPage": "pages",
            "cpaExtensions": {},
            "recurrentEnabled": False,
            "selectedCardId": "",
            "cardRegistrationEnabled": False,
            "aftEnabled": False,
            "aftMirExtensionType": "3ds2.destAbroadPAN",
            "aftMirExtensionValue": "BLR411xxxxxxxxx1111"
        }

def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
    except Exception as e:
        pass

def load_cards():
    try:
        if os.path.exists(CARDS_FILE):
            with open(CARDS_FILE, "r", encoding="utf-8") as f:
                cards = json.load(f)
                return cards[-50:]
        return []
    except Exception as e:
        return []

def save_card(card_data):
    try:
        if not os.path.exists(CARDS_FILE):
            with open(CARDS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        
        cards = load_cards()
        cards = [card for card in cards if card.get("card_id") != card_data.get("card_id")]
        
        cards.append({
            "card_id": card_data.get("card_id"),
            "masked_pan": card_data.get("masked_pan", ""),
            "expiry": card_data.get("expiry", ""),
            "payment_system": card_data.get("payment_system", ""),
            "timestamp": datetime.now().isoformat(),
            "registered": card_data.get("registered", "N")
        })
        
        cards = cards[-50:]
        
        with open(CARDS_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass

def get_next_order_id():
    try:
        if os.path.exists(ORDER_COUNTER_FILE):
            with open(ORDER_COUNTER_FILE, "r") as f:
                counter = int(f.read().strip())
        else:
            counter = 0
    except:
        counter = 0
    
    counter += 1
    
    try:
        with open(ORDER_COUNTER_FILE, "w") as f:
            f.write(str(counter))
    except Exception as e:
        pass
    
    return str(counter)

def load_callbacks():
    if os.path.exists(CALLBACKS_FILE):
        try:
            with open(CALLBACKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_callback(token, data):
    try:
        callbacks = load_callbacks()
        callbacks = [cb for cb in callbacks if cb["token"] != token]
        
        callbacks.append({
            "token": token,
            "timestamp": datetime.now().isoformat(),
            "data": data
        })
        callbacks = callbacks[-50:]
        with open(CALLBACKS_FILE, "w", encoding="utf-8") as f:
            json.dump(callbacks, f, ensure_ascii=False, indent=2)
            
        if data.get("type") == "RPReq":
            raw_params = data.get("raw_params", {})
            card_id = raw_params.get("card.id")
            
            if card_id:
                card_data = {
                    "card_id": card_id,
                    "masked_pan": raw_params.get("p.maskedPan", ""),
                    "expiry": raw_params.get("card.expiry", ""),
                    "payment_system": raw_params.get("p.paymentSystem", ""),
                    "registered": raw_params.get("card.registered", "N")
                }
                save_card(card_data)
    except Exception as e:
        pass

@tester_bp.route("/")
def index():
    settings = load_settings()
    cards = load_cards()
    return render_template("tester.html", settings=settings, cards=cards)

@tester_bp.route("/create_order", methods=["POST"])
def create_order():
    try:
        settings = load_settings()
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "No JSON data"})
            
        mode = data.get("mode", "test")
        extra_param = data.get("extraParam", "")
        payment_page = data.get("paymentPage", "pages")
        recurrent_enabled = data.get("recurrentEnabled", False)
        selected_card_id = data.get("selectedCardId", "")
        card_registration_enabled = data.get("cardRegistrationEnabled", False)
        aft_enabled = data.get("aftEnabled", False)
        aft_mir_extension_type = data.get("aftMirExtensionType", "")
        aft_mir_extension_value = data.get("aftMirExtensionValue", "")
        
        order_id = get_next_order_id()
        amount = settings.get("amount", 100)
        
        # Если включена регистрация карт, используем pages-rec
        if card_registration_enabled:
            payment_page = "pages-rec"
        
        # Если включен AFT платеж, добавляем paymentId=aft
        if aft_enabled:
            if extra_param:
                extra_param += "&paymentId=aft"
            else:
                extra_param = "paymentId=aft"
        
        initiation_link = (
            f"https://lt.pga.gazprombank.ru/{payment_page}/?"
            f"lang_code=RU&merch_id=ECOM_CPA&back_url_s={settings.get('backUrlSuccess', '')}"
            f"&back_url_f={settings.get('backUrlFail', '')}&o.order_id={order_id}&mode={mode}&amount={amount}"
        )
        
        if extra_param:
            initiation_link += f"&{extra_param}"
            
        if recurrent_enabled and selected_card_id:
            initiation_link += f"&src.type=card_id&src.cardId={selected_card_id}"
        
        return jsonify({
            "initiation_link": initiation_link, 
            "success": True,
            "order_id": order_id,
            "aft_enabled": aft_enabled,
            "aft_mir_extension_type": aft_mir_extension_type,
            "aft_mir_extension_value": aft_mir_extension_value
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@tester_bp.route("/save_settings", methods=["POST"])
def save_settings_route():
    data = request.get_json()
    settings = load_settings()
    
    settings.update({
        "amount": data.get("amount", settings.get("amount", 100)),
        "shortDesc": data.get("shortDesc", settings.get("shortDesc", "Короткое описание")),
        "longDesc": data.get("longDesc", settings.get("longDesc", "Описание по умолчанию")),
        "backUrlSuccess": data.get("backUrlSuccess", settings.get("backUrlSuccess")),
        "backUrlFail": data.get("backUrlFail", settings.get("backUrlFail")),
        "extraParam": data.get("extraParam", settings.get("extraParam", "")),
        "paymentPage": data.get("paymentPage", settings.get("paymentPage", "pages")),
        "recurrentEnabled": data.get("recurrentEnabled", False),
        "selectedCardId": data.get("selectedCardId", ""),
        "cardRegistrationEnabled": data.get("cardRegistrationEnabled", False),
        "aftEnabled": data.get("aftEnabled", False),
        "aftMirExtensionType": data.get("aftMirExtensionType", "3ds2.destAbroadPAN"),
        "aftMirExtensionValue": data.get("aftMirExtensionValue", "")
    })
    
    cpa_extensions = data.get("cpaExtensions", {})
    if isinstance(cpa_extensions, dict):
        settings["cpaExtensions"] = cpa_extensions
    else:
        settings["cpaExtensions"] = {}
    
    save_settings(settings)
    return jsonify({"success": True})

@tester_bp.route("/get_callbacks", methods=["GET"])
def get_callbacks():
    callbacks = load_callbacks()
    return jsonify({"success": True, "callbacks": callbacks})

@tester_bp.route("/get_callback_details", methods=["GET"])
def get_callback_details():
    token = request.args.get("token")
    callbacks = load_callbacks()
    for callback in callbacks:
        if callback["token"] == token:
            return jsonify({"success": True, "data": callback["data"]})
    return jsonify({"success": False, "error": "Callback not found"})

@tester_bp.route("/get_cards", methods=["GET"])
def get_cards():
    cards = load_cards()
    return jsonify({"success": True, "cards": cards})
