import os
import re
import webbrowser
from flask import Flask, request, jsonify, render_template
from botok import WordTokenizer

import sys

# Определяем правильный путь к папке templates для .exe
if getattr(sys, 'frozen', False):
    # Если запущен .exe, берем путь к папке рядом с экзешником
    base_dir = os.path.dirname(sys.executable)
    template_folder = os.path.join(base_dir, 'templates')
else:
    # Если запущен обычный python app.py
    template_folder = 'templates'

app = Flask(__name__, template_folder=template_folder)


DSL_DICTIONARIES = {}
STAR_DICTS = {}
DICTIONARY_NAMES = []

def load_dsl_file(filepath):
    dict_name = os.path.basename(filepath).replace('.dsl', '')
    entries = {}
    
    for encoding in ['utf-16-le', 'utf-16-be', 'utf-16', 'utf-8']:
        try:
            with open(filepath, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read()
            if content and len(content) > 10:
                break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        print(f"❌ Не удалось прочитать файл {filepath}")
        return {}

    lines = content.split('\n')
    current_words = []
    current_definition = []

    for line in lines:
        if line.startswith('#') or not line.strip():
            continue
            
        # Если строка не начинается с отступа — это заголовок (тибетское слово)
        if not line.startswith('\t') and not line.startswith(' '):
            if current_words and current_definition:
                full_def = "\n".join(current_definition).strip()
                for w in current_words:
                    if w in entries:
                        entries[w] += "\n\n" + full_def
                    else:
                        entries[w] = full_def
            
            word = line.strip().strip('་')
            if word:
                current_words = [word]
                current_definition = []
        else:
            line_clean = line
            
            # 1. Счищаем ломаные слэши у авторов внутри скобок ([RY\] -> [RY], [IW\] -> [IW])
            line_clean = re.sub(r'\\\]', ']', line_clean)
            
            # 2. Исправляем двойные сломанные скобки ([[p] -> [p])
            line_clean = re.sub(r'\[\[', '[', line_clean)
            
            # 3. Полностью удаляем ТЕХНИЧЕСКИЙ мусор (отступы, цвета, зоны трансляции trn/trs)
            # Удаляем [m1], [m2], [/m], [trn], [/trn], [!trs], [/!trs]
            line_clean = re.sub(r'\[/?(m\d*|trn|!trs)\]', '', line_clean)
            # Удаляем стили оформления [c цвет], [/c], [b], [/b], [i], [/i]
            line_clean = re.sub(r'\[/?(c|b|i|u|p|sub|sup).*?\]', '', line_clean)
            
            # 4. Убираем висящие системные слэши DSL только на самом конце строки
            line_clean = line_clean.strip()
            if line_clean.endswith('\\'):
                line_clean = line_clean[:-1].strip()
            
            if line_clean:
                current_definition.append(line_clean)
                
    if current_words and current_definition:
        full_def = "\n".join(current_definition).strip()
        for w in current_words:
            if w in entries:
                entries[w] += "\n\n" + full_def
            else:
                entries[w] = full_def
        
    print(f"📖 Загружен DSL словарь: {dict_name} ({len(entries)} статей)")
    return entries




def init_all_dictionaries():
    global DICTIONARY_NAMES, DSL_DICTIONARIES, STAR_DICTS
    
    # ИСПРАВЛЕНО: Умный поиск внешней папки dicts рядом с .exe или скриптом
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    dict_dir = os.path.join(base_dir, 'dicts')
    
    print(f"🔍 Ищем словари по пути: {dict_dir}")
    
    if not os.path.exists(dict_dir):
        os.makedirs(dict_dir)
        print(f"📁 Создана пустая папка для словарей: '{dict_dir}'")
        return

    for file in os.listdir(dict_dir):
        if file.endswith('.dsl'):
            name = file.replace('.dsl', '')
            DSL_DICTIONARIES[name] = load_dsl_file(os.path.join(dict_dir, file))
            if name not in DICTIONARY_NAMES:
                DICTIONARY_NAMES.append(name)

    try:
        from pystardict import Dictionary
        for file in os.listdir(dict_dir):
            if file.endswith('.ifo'):
                name = file.replace('.ifo', '')
                base_path = os.path.join(dict_dir, name)
                STAR_DICTS[name] = Dictionary(base_path)
                if name not in DICTIONARY_NAMES:
                    DICTIONARY_NAMES.append(name)
                print(f"📖 Загружен StarDict словарь: {name}")
    except ImportError:
         print("⚠️ Библиотека pystardict отсутствует.")


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/parse', methods=['POST'])
def parse_text():
    data = request.json
    raw_text = data.get('text', '')
    
    wt = WordTokenizer()
    tokens = wt.tokenize(raw_text)
    
    processed_tokens = []
    unique_words_to_lookup = set()
    
    for token in tokens:
        t_type = "WORD"
        if token.chunk_type == "SPACE":
            t_type = "SPACE"
        elif token.pos == "PUNCT":
            t_type = "PUNCT"
            
        word_clean = token.text_cleaned.strip('་')
        lemma_clean = token.lemma.strip('་')
        
        processed_tokens.append({
            "text": token.text,
            "text_cleaned": word_clean,
            "lemma": lemma_clean,
            "type": t_type
        })
        
        if t_type == "WORD" and word_clean:
            unique_words_to_lookup.add(word_clean)
            unique_words_to_lookup.add(lemma_clean)

    text_dictionary_cache = {}
    
    for word in unique_words_to_lookup:
        translations_by_dict = {}
        
        for dict_name, dict_data in DSL_DICTIONARIES.items():
            if word in dict_data:
                if dict_name not in translations_by_dict:
                    translations_by_dict[dict_name] = []
                translations_by_dict[dict_name].append(dict_data[word])
                
        # Поиск по StarDict словарям
        for dict_name, sd_obj in STAR_DICTS.items():
            if word in sd_obj:
                if dict_name not in translations_by_dict:
                    translations_by_dict[dict_name] = []
                raw_sd_text = sd_obj[word]
                if isinstance(raw_sd_text, bytes):
                    raw_sd_text = raw_sd_text.decode('utf-8', errors='ignore')
                
                # ИСПРАВЛЕНО: Мы БОЛЬШЕ НЕ УДАЛЯЕМ теги <br> и синий цвет!
                # Передаем оригинальный HTML-текст напрямую на страницу
                translations_by_dict[dict_name].append(raw_sd_text.strip())


                
        if translations_by_dict:
            text_dictionary_cache[word] = translations_by_dict

    return jsonify({
        "tokens": processed_tokens,
        "dictionary": text_dictionary_cache,
        "dictionary_names": DICTIONARY_NAMES
    })

if __name__ == '__main__':
    print("⏳ Загрузка словарных баз из папки dicts...")
    init_all_dictionaries()
    webbrowser.open("http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=False)
