import math

# --- FUNCIONES HELPER PARA PARSEO Y FORMATEO (ADAPTADAS) ---


def parse_ah_to_number_of(ah_line_str: str):
    if not isinstance(ah_line_str, str):
        return None
    s = ah_line_str.strip().replace(' ', '')
    if not s or s in ['-', '?']:
        return None
    original_starts_with_minus = ah_line_str.strip().startswith('-')
    try:
        if '/' in s:  # Formatos como "0.5/1", "-0/0.5"
            parts = s.split('/')
            if len(parts) != 2:
                return None
            p1_str, p2_str = parts[0], parts[1]
            try:
                val1 = float(p1_str)
            except ValueError:
                return None
            try:
                val2 = float(p2_str)
            except ValueError:
                return None
            # Lógica para manejar signos correctamente en formatos como "-0/0.5" o "0/-0.5"
            if val1 < 0 and not p2_str.startswith('-') and val2 > 0:  # ej: -0.5/1
                val2 = -abs(val2)  # Implícito -0.5 / -1, pero raro; más común es -0.5/-1
            elif original_starts_with_minus and val1 == 0.0 and \
                 (p1_str == "0" or p1_str == "-0") and \
                 not p2_str.startswith('-') and val2 > 0:  # ej: -0/0.5 (debe ser 0 y -0.5)
                val2 = -abs(val2)
            return (val1 + val2) / 2.0
        else:  # Formatos como "0.5", "-1"
            return float(s)
    except ValueError:
        return None


def format_ah_as_decimal_string_of(ah_line_str: str, for_sheets=False):
    # Devuelve el string formateado (ej: "-0.5", "1", "0") o '-' si no es parseable/válido.
    if not isinstance(ah_line_str, str) or not ah_line_str.strip() or ah_line_str.strip() in ['-', '?']:
        return ah_line_str.strip() if isinstance(ah_line_str, str) and ah_line_str.strip() in ['-', '?'] else '-'
    
    numeric_value = parse_ah_to_number_of(ah_line_str)
    if numeric_value is None:  # No se pudo parsear a número
        return ah_line_str.strip() if ah_line_str.strip() in ['-', '?'] else '-'

    if numeric_value == 0.0:
        return "0"
    
    sign = -1 if numeric_value < 0 else 1
    abs_num = abs(numeric_value)
    mod_val = abs_num % 1
    
    if mod_val == 0.0:
        abs_rounded = abs_num
    elif mod_val == 0.25:
        abs_rounded = math.floor(abs_num) + 0.25
    elif mod_val == 0.5:
        abs_rounded = abs_num
    elif mod_val == 0.75:
        abs_rounded = math.floor(abs_num) + 0.75
    else:
        if mod_val < 0.25:
            abs_rounded = math.floor(abs_num)
        elif mod_val < 0.75:
            abs_rounded = math.floor(abs_num) + 0.5
        else:
            abs_rounded = math.ceil(abs_num)

    final_value_signed = sign * abs_rounded

    if final_value_signed == 0.0:
        output_str = "0"
    elif abs(final_value_signed - round(final_value_signed, 0)) < 1e-9:
        output_str = str(int(round(final_value_signed, 0)))
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.5)) < 1e-9:
        output_str = f"{final_value_signed:.1f}"
    elif abs(final_value_signed - (math.floor(final_value_signed) + 0.25)) < 1e-9 or \
         abs(final_value_signed - (math.floor(final_value_signed) + 0.75)) < 1e-9:
        output_str = f"{final_value_signed:.2f}".replace(".25", ".25").replace(".75", ".75")
    else:
        output_str = f"{final_value_signed:.2f}"

    if for_sheets:
        return "'" + output_str.replace('.', ',') if output_str not in ['-', '?'] else output_str
    return output_str
