from flask import Flask, request, Response
import json
import os
import sys
from datetime import datetime
import re

app = Flask(__name__)

# Исправляем пути - api_server.py находится в /home/***/bot/
# а настройки в /home/***/tester/
SETTINGS_PATH = "/home/***/settings.json"
CALLBACKS_FILE = "/home/***/callbacks.json"

def load_settings():
    print(f"DEBUG: Loading settings from: {SETTINGS_PATH}", file=sys.stderr)
    print(f"DEBUG: File exists: {os.path.exists(SETTINGS_PATH)}", file=sys.stderr)
    
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                settings = json.load(f)
                print(f"DEBUG: Loaded settings - aftEnabled: {settings.get('aftEnabled', False)}", file=sys.stderr)
                print(f"DEBUG: AFT mir extension type: {settings.get('aftMirExtensionType')}", file=sys.stderr)
                print(f"DEBUG: AFT mir extension value: {settings.get('aftMirExtensionValue')}", file=sys.stderr)
                print(f"DEBUG: AFT mir extension country: {settings.get('aftMirExtensionCountry')}", file=sys.stderr)
                print(f"DEBUG: AFT mir extension phone: {settings.get('aftMirExtensionPhone')}", file=sys.stderr)
                print(f"DEBUG: CPA extensions: {settings.get('cpaExtensions', {})}", file=sys.stderr)
                return settings
        except Exception as e:
            print(f"DEBUG: Error loading settings: {e}", file=sys.stderr)
            pass
    else:
        print(f"DEBUG: Settings file not found at {SETTINGS_PATH}!", file=sys.stderr)
    
    # Возвращаем настройки по умолчанию
    default_settings = {
        "amount": "100",
        "shortDesc": "Короткое описание",
        "longDesc": "Описание по умолчанию",
        "backUrlSuccess": "https://tda-photo.ru/success",
        "backUrlFail": "https://tda-photo.ru/fail",
        "extraParam": "",
        "cpaExtensions": {},
        "recurrentEnabled": False,
        "selectedCardId": "",
        "cardRegistrationEnabled": False,
        "aftEnabled": False,
        "aftMirExtensionType": "3ds2.destAbroadPAN",
        "aftMirExtensionValue": "411111******1111",
        "aftMirExtensionCountry": "BLR",
        "aftMirExtensionPhone": ""
    }
    print(f"DEBUG: Using default settings: {default_settings}", file=sys.stderr)
    return default_settings

def normalize_value_for_type(value, extension_type, country):
    """
    Нормализует значение в зависимости от типа расширения.
    Возвращает кортеж (value, phone)
    """
    if not value:
        return value, ""
    
    value = str(value).strip()
    
    # Для PAN: номер карты, может быть замаскирован
    if extension_type == "3ds2.destAbroadPAN":
        # Удаляем возможный префикс страны из начала
        if value.upper().startswith("BLR"):
            value = value[3:]
        elif value.upper().startswith("RUS"):
            value = value[3:]
        return value, ""
    
    # Для IBAN: удаляем код страны из начала если он там
    if extension_type == "3ds2.destAbroadIBAN":
        # Проверяем, начинается ли с 3-буквенного кода страны
        if len(value) >= 3 and value[:3].isalpha() and value[:3].isupper():
            possible_country = value[:3]
            if possible_country in ["BLR", "RUS", "KAZ", "UKR", "DEU", "USA", "GBR", "CHN"]:
                value = value[3:]
        return value, ""
    
    # Для SWIFT: нужно отделить SWIFT код от телефона если они вместе
    if extension_type == "3ds2.destAbroadSWIFT":
        # SWIFT код обычно 8 или 11 символов (буквы/цифры)
        swift_pattern = r'^([A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?)'
        match = re.match(swift_pattern, value)
        
        if match:
            swift_code = match.group(1)
            # Остаток может быть телефоном
            remaining = value[len(swift_code):].strip()
            phone = remaining if remaining else ""
            
            # Если телефон не указан, используем настройку из phone
            if not phone:
                return swift_code, ""
            
            # Удаляем возможный код страны из телефона
            if phone.startswith("375") or phone.startswith("7") or phone.startswith("+375") or phone.startswith("+7"):
                return swift_code, phone
            
            return swift_code, phone
        else:
            # Если не соответствует паттерну SWIFT, возвращаем как есть
            return value, ""
    
    return value, ""

def build_cpa_extensions_xml(extensions, aft_enabled=False, 
                            aft_mir_extension_type=None, 
                            aft_mir_extension_value=None,
                            aft_mir_extension_country=None,
                            aft_mir_extension_phone=None):
    """
    Собирает XML для расширений CPA согласно документации v.1.1
    Для AFT операций добавляет <mir-extension> с корректными тегами
    """
    xml_parts = []
    
    # Добавляем стандартные расширения CPA
    if 'submerchant-data' in extensions:
        submerchant = extensions['submerchant-data']
        submerchant_xml = "<submerchant-data>"
        fields = ["city", "country", "id", "name", "terminal-id", "mcc", "inn"]
        for field in fields:
            if field in submerchant:
                submerchant_xml += f"<{field}>{submerchant[field]}</{field}>"
        submerchant_xml += "</submerchant-data>"
        xml_parts.append(submerchant_xml)
    
    if 'order-params' in extensions and isinstance(extensions['order-params'], list):
        order_params_xml = "<order-params>"
        for param in extensions['order-params']:
            if isinstance(param, dict) and 'name' in param and 'value' in param:
                order_params_xml += f"<param><name>{param['name']}</name><value>{param['value']}</value></param>"
        order_params_xml += "</order-params>"
        xml_parts.append(order_params_xml)
    
    # Добавляем AFT mir-extension если включен AFT
    if aft_enabled and aft_mir_extension_type:
        print(f"DEBUG: Building mir-extension for AFT with type: {aft_mir_extension_type}", file=sys.stderr)
        print(f"DEBUG: Original value: {aft_mir_extension_value}", file=sys.stderr)
        print(f"DEBUG: Original country: {aft_mir_extension_country}", file=sys.stderr)
        print(f"DEBUG: Original phone: {aft_mir_extension_phone}", file=sys.stderr)
        
        # Нормализуем значение в зависимости от типа
        normalized_value, extracted_phone = normalize_value_for_type(
            aft_mir_extension_value, 
            aft_mir_extension_type,
            aft_mir_extension_country
        )
        
        print(f"DEBUG: Normalized value: {normalized_value}", file=sys.stderr)
        print(f"DEBUG: Extracted phone: {extracted_phone}", file=sys.stderr)
        
        # Определяем телефон для использования
        # Приоритет: 1) настройка phone, 2) извлеченный телефон, 3) пустая строка
        phone_to_use = aft_mir_extension_phone or extracted_phone
        
        # Определяем страну для использования
        country_to_use = aft_mir_extension_country
        if not country_to_use:
            # Если страна не указана, используем BLR по умолчанию для всех типов
            country_to_use = "BLR"
            print(f"DEBUG: Using default country: {country_to_use}", file=sys.stderr)
        
        # Формируем mir-extension согласно примерам из документации
        mir_extension_xml = "<mir-extension>"
        mir_extension_xml += f"\n  <type>{aft_mir_extension_type}</type>"
        
        # Добавляем значение
        if normalized_value:
            mir_extension_xml += f"\n  <value>{normalized_value}</value>"
        elif aft_mir_extension_value:
            mir_extension_xml += f"\n  <value>{aft_mir_extension_value}</value>"
        
        # ВСЕГДА добавляем country для всех трех типов
        if country_to_use:
            mir_extension_xml += f"\n  <country>{country_to_use}</country>"
        
        # Добавляем телефон ТОЛЬКО для типа destAbroadSWIFT согласно документации
        if aft_mir_extension_type == "3ds2.destAbroadSWIFT" and phone_to_use:
            # Убедимся, что телефон в правильном формате (только цифры)
            phone_digits = re.sub(r'\D', '', phone_to_use)
            if phone_digits:
                mir_extension_xml += f"\n  <phone>{phone_digits}</phone>"
        
        mir_extension_xml += "\n</mir-extension>"
        xml_parts.append(mir_extension_xml)
        
        # Для AFT операций всегда добавляем transaction-type AFT
        xml_parts.append("<transaction-type>AFT</transaction-type>")
    else:
        # Если не AFT, используем стандартный transaction-type из настроек
        transaction_type = extensions.get('transaction-type', 'Payment')
        if transaction_type in ['CardRegister', 'Payment', 'AFT', 'OCT', 'P2P']:
            xml_parts.append(f"<transaction-type>{transaction_type}</transaction-type>")
    
    return "\n".join(xml_parts)

@app.route("/operation/check", methods=["GET", "POST"])
def operation_check():
    settings = load_settings()

    order_id = request.args.get("o.order_id") or "1"
    token = request.args.get("trx_id")
    
    if token:
        try:
            sys.path.insert(0, '/home/***/website')
            from tester import save_callback
            cpa_data = {
                "type": "CPAReq",
                "timestamp": datetime.now().isoformat(),
                "token": token,
                "raw_params": dict(request.args)
            }
            save_callback(token, cpa_data)
        except Exception as e:
            print(f"DEBUG: Error saving callback: {e}", file=sys.stderr)
            pass
    
    # Проверяем параметр paymentId для определения AFT
    payment_id = request.args.get("paymentId", "")
    aft_enabled = payment_id == "aft"
    
    print(f"DEBUG: paymentId from request: {payment_id}", file=sys.stderr)
    print(f"DEBUG: aft_enabled calculated: {aft_enabled}", file=sys.stderr)
    print(f"DEBUG: settings aftEnabled: {settings.get('aftEnabled', False)}", file=sys.stderr)
    
    # Если AFT включен в запросе или в настройках, используем AFT
    use_aft = aft_enabled or settings.get('aftEnabled', False)
    
    # Создаем копию extensions, чтобы не модифицировать оригинальные настройки
    extensions = settings.get('cpaExtensions', {}).copy()
    
    # Если используем AFT, удаляем transaction-type из extensions чтобы избежать дублирования
    if use_aft and 'transaction-type' in extensions:
        del extensions['transaction-type']
    
    cpa_extensions_xml = build_cpa_extensions_xml(
        extensions,
        use_aft,
        settings.get('aftMirExtensionType'),
        settings.get('aftMirExtensionValue'),
        settings.get('aftMirExtensionCountry'),
        settings.get('aftMirExtensionPhone')
    )
    
    card_xml = ""
    if settings.get('recurrentEnabled') and settings.get('selectedCardId'):
        card_xml = f"""  <card>
    <id>{settings['selectedCardId']}</id>
    <present>N</present>
  </card>"""
    
    # Добавляем transaction-type для регистрации карт (только если не AFT)
    transaction_type_xml = ""
    if settings.get('cardRegistrationEnabled') and not use_aft:
        transaction_type_xml = "  <transaction-type>CardRegister</transaction-type>"
    
    print(f"DEBUG: use_aft: {use_aft}", file=sys.stderr)
    print(f"DEBUG: transaction_type_xml: {transaction_type_xml}", file=sys.stderr)
    print(f"DEBUG: cpa_extensions_xml:\n{cpa_extensions_xml}", file=sys.stderr)
    
    # Формируем XML ответ, правильно комбинируя все части
    xml_parts = [
        """<?xml version='1.0' standalone='yes'?>
<payment-avail-response>
  <result>
    <code>1</code>
    <desc>Payment is available</desc>
  </result>
  <merchant-trx>{order_id}</merchant-trx>
  <purchase>
    <shortDesc>{short_desc}</shortDesc>
    <longDesc>{long_desc}</longDesc>
    <account-amount>
      <id>MAIN</id>
      <amount>{amount}</amount>
      <currency>643</currency>
      <exponent>2</exponent>
    </account-amount>
  </purchase>""".format(
        order_id=order_id,
        short_desc=settings.get('shortDesc', 'Короткое описание'),
        long_desc=settings.get('longDesc', 'Описание по умолчанию'),
        amount=settings['amount']
    )
    ]
    
    # Добавляем card_xml если он есть
    if card_xml:
        xml_parts.append(card_xml)
    
    # Добавляем cpa_extensions_xml если он есть
    if cpa_extensions_xml:
        # Разделяем на строки и добавляем с правильным отступом
        for line in cpa_extensions_xml.split('\n'):
            if line.strip():  # Пропускаем пустые строки
                # Первая строка уже имеет отступ 2 пробела
                if line.startswith("  "):
                    xml_parts.append(line)
                else:
                    xml_parts.append(f"  {line}")
    
    # Добавляем transaction_type_xml если он есть (только для CardRegister и не для AFT)
    if transaction_type_xml:
        xml_parts.append(transaction_type_xml)
    
    # Закрываем XML
    xml_parts.append("</payment-avail-response>")
    
    # Объединяем все части
    xml_response = "\n".join(xml_parts)

    print(f"DEBUG: Final XML response:\n{xml_response}", file=sys.stderr)
    return Response(xml_response, mimetype="text/xml")

@app.route("/operation/callback", methods=["GET", "POST"])
def operation_callback():
    trx_id = request.args.get("trx_id")
    
    if trx_id:
        try:
            sys.path.insert(0, '/home/***/website')
            from tester import save_callback
            callback_data = {
                "type": "RPReq",
                "timestamp": datetime.now().isoformat(),
                "token": trx_id,
                "raw_params": dict(request.args)
            }
            save_callback(trx_id, callback_data)
        except Exception as e:
            print(f"DEBUG: Error saving RPReq callback: {e}", file=sys.stderr)
            pass

    result_code = request.args.get("result_code") or "1"
    
    if result_code == "1":
        xml_response = """<?xml version='1.0' standalone='yes'?>
<register-payment-response>
  <result>
    <code>1</code>
    <desc>OK</desc>
  </result>
</register-payment-response>"""
    else:
        xml_response = """<?xml version='1.0' standalone='yes'?>
<register-payment-response>
  <result>
    <code>2</code>
    <desc>FAILED</desc>
  </result>
</register-payment-response>"""

    return Response(xml_response, mimetype="text/xml")

@app.route("/ping")
def ping():
    return {"status": "ok", "time": datetime.now().isoformat()}

if __name__ == "__main__":
    print("DEBUG: Starting API server with debug output", file=sys.stderr)
    app.run(host="0.0.0.0", port=7443, debug=True)
