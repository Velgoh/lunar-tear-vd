#pragma once

#include <string>
#include <vector>
#include <memory>
#include <sstream>
#include <iomanip>
#include <stdexcept>
#include <cctype>
#include <cmath>

namespace json {

enum class Type {
    Null,
    Bool,
    Number,
    String,
    Array,
    Object
};

class Value {
public:
    Type type = Type::Null;
    bool bool_val = false;
    double num_val = 0.0;
    std::string str_val;
    std::vector<Value> arr_val;
    std::vector<std::pair<std::string, Value>> obj_val;

    Value() : type(Type::Null) {}
    Value(std::nullptr_t) : type(Type::Null) {}
    Value(bool b) : type(Type::Bool), bool_val(b) {}
    Value(int n) : type(Type::Number), num_val(n) {}
    Value(long long n) : type(Type::Number), num_val(static_cast<double>(n)) {}
    Value(double n) : type(Type::Number), num_val(n) {}
    Value(const char* s) : type(Type::String), str_val(s ? s : "") {}
    Value(const std::string& s) : type(Type::String), str_val(s) {}

    static Value object() {
        Value v;
        v.type = Type::Object;
        return v;
    }

    static Value array() {
        Value v;
        v.type = Type::Array;
        return v;
    }

    bool is_null() const { return type == Type::Null; }
    bool is_bool() const { return type == Type::Bool; }
    bool is_number() const { return type == Type::Number; }
    bool is_string() const { return type == Type::String; }
    bool is_array() const { return type == Type::Array; }
    bool is_object() const { return type == Type::Object; }

    bool as_bool(bool def = false) const {
        return is_bool() ? bool_val : def;
    }

    double as_double(double def = 0.0) const {
        return is_number() ? num_val : def;
    }

    int as_int(int def = 0) const {
        return is_number() ? static_cast<int>(std::round(num_val)) : def;
    }

    std::string as_string(const std::string& def = "") const {
        return is_string() ? str_val : def;
    }

    bool contains(const std::string& key) const {
        if (!is_object()) return false;
        for (const auto& kv : obj_val) {
            if (kv.first == key) return true;
        }
        return false;
    }

    const Value* find(const std::string& key) const {
        if (!is_object()) return nullptr;
        for (const auto& kv : obj_val) {
            if (kv.first == key) return &kv.second;
        }
        return nullptr;
    }

    Value* find(const std::string& key) {
        if (!is_object()) return nullptr;
        for (auto& kv : obj_val) {
            if (kv.first == key) return &kv.second;
        }
        return nullptr;
    }

    Value& operator[](const std::string& key) {
        if (!is_object()) {
            type = Type::Object;
            obj_val.clear();
        }
        for (auto& kv : obj_val) {
            if (kv.first == key) return kv.second;
        }
        obj_val.push_back({key, Value()});
        return obj_val.back().second;
    }

    const Value& operator[](const std::string& key) const {
        static Value null_val;
        const Value* ptr = find(key);
        return ptr ? *ptr : null_val;
    }

    Value& operator[](size_t index) {
        if (!is_array()) {
            type = Type::Array;
            arr_val.clear();
        }
        if (index >= arr_val.size()) {
            arr_val.resize(index + 1);
        }
        return arr_val[index];
    }

    const Value& operator[](size_t index) const {
        static Value null_val;
        if (is_array() && index < arr_val.size()) {
            return arr_val[index];
        }
        return null_val;
    }

    void push_back(const Value& v) {
        if (!is_array()) {
            type = Type::Array;
            arr_val.clear();
        }
        arr_val.push_back(v);
    }

    size_t size() const {
        if (is_array()) return arr_val.size();
        if (is_object()) return obj_val.size();
        return 0;
    }

    std::string dump(int indent = 4, int current_indent = 0) const {
        std::ostringstream ss;
        std::string ind(current_indent, ' ');
        std::string next_ind(current_indent + indent, ' ');

        switch (type) {
            case Type::Null:
                ss << "null";
                break;
            case Type::Bool:
                ss << (bool_val ? "true" : "false");
                break;
            case Type::Number: {
                if (std::isnan(num_val) || std::isinf(num_val)) {
                    ss << "0.0";
                } else {
                    double intpart;
                    if (std::modf(num_val, &intpart) == 0.0 && std::abs(num_val) < 1e15) {
                        ss << static_cast<long long>(num_val);
                    } else {
                        ss << std::setprecision(17) << num_val;
                    }
                }
                break;
            }
            case Type::String: {
                ss << '"';
                for (char c : str_val) {
                    if (c == '"') ss << "\\\"";
                    else if (c == '\\') ss << "\\\\";
                    else if (c == '\b') ss << "\\b";
                    else if (c == '\f') ss << "\\f";
                    else if (c == '\n') ss << "\\n";
                    else if (c == '\r') ss << "\\r";
                    else if (c == '\t') ss << "\\t";
                    else if (static_cast<unsigned char>(c) < 32) {
                        ss << "\\u00" << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(c) << std::dec;
                    } else {
                        ss << c;
                    }
                }
                ss << '"';
                break;
            }
            case Type::Array: {
                if (arr_val.empty()) {
                    ss << "[]";
                } else {
                    ss << "[\n";
                    for (size_t i = 0; i < arr_val.size(); ++i) {
                        ss << next_ind << arr_val[i].dump(indent, current_indent + indent);
                        if (i + 1 < arr_val.size()) ss << ",";
                        ss << "\n";
                    }
                    ss << ind << "]";
                }
                break;
            }
            case Type::Object: {
                if (obj_val.empty()) {
                    ss << "{}";
                } else {
                    ss << "{\n";
                    for (size_t i = 0; i < obj_val.size(); ++i) {
                        ss << next_ind << '"' << obj_val[i].first << "\": "
                           << obj_val[i].second.dump(indent, current_indent + indent);
                        if (i + 1 < obj_val.size()) ss << ",";
                        ss << "\n";
                    }
                    ss << ind << "}";
                }
                break;
            }
        }
        return ss.str();
    }
};

class Parser {
    const std::string& src;
    size_t pos = 0;

    void skip_whitespace() {
        while (pos < src.size()) {
            char c = src[pos];
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                pos++;
            } else if (c == '/' && pos + 1 < src.size() && src[pos + 1] == '/') {
                pos += 2;
                while (pos < src.size() && src[pos] != '\n') pos++;
            } else {
                break;
            }
        }
    }

    char peek() {
        skip_whitespace();
        return (pos < src.size()) ? src[pos] : '\0';
    }

    char get() {
        skip_whitespace();
        return (pos < src.size()) ? src[pos++] : '\0';
    }

public:
    Parser(const std::string& s) : src(s) {}

    Value parse() {
        skip_whitespace();
        Value v = parse_value();
        skip_whitespace();
        return v;
    }

private:
    Value parse_value() {
        skip_whitespace();
        if (pos >= src.size()) return Value();
        char c = src[pos];
        if (c == 'n') return parse_null();
        if (c == 't' || c == 'f') return parse_bool();
        if (c == '"') return parse_string();
        if (c == '[') return parse_array();
        if (c == '{') return parse_object();
        if (c == '-' || std::isdigit(static_cast<unsigned char>(c))) return parse_number();
        return Value();
    }

    Value parse_null() {
        if (src.compare(pos, 4, "null") == 0) {
            pos += 4;
            return Value();
        }
        return Value();
    }

    Value parse_bool() {
        if (src.compare(pos, 4, "true") == 0) {
            pos += 4;
            return Value(true);
        }
        if (src.compare(pos, 5, "false") == 0) {
            pos += 5;
            return Value(false);
        }
        return Value();
    }

    Value parse_number() {
        size_t start = pos;
        if (pos < src.size() && src[pos] == '-') pos++;
        while (pos < src.size() && std::isdigit(static_cast<unsigned char>(src[pos]))) pos++;
        if (pos < src.size() && src[pos] == '.') {
            pos++;
            while (pos < src.size() && std::isdigit(static_cast<unsigned char>(src[pos]))) pos++;
        }
        if (pos < src.size() && (src[pos] == 'e' || src[pos] == 'E')) {
            pos++;
            if (pos < src.size() && (src[pos] == '+' || src[pos] == '-')) pos++;
            while (pos < src.size() && std::isdigit(static_cast<unsigned char>(src[pos]))) pos++;
        }
        if (start == pos) return Value(0.0);
        try {
            double n = std::stod(src.substr(start, pos - start));
            return Value(n);
        } catch (...) {
            return Value(0.0);
        }
    }

    Value parse_string() {
        pos++; // skip opening '"'
        std::string s;
        while (pos < src.size()) {
            char c = src[pos++];
            if (c == '"') return Value(s);
            if (c == '\\' && pos < src.size()) {
                char esc = src[pos++];
                if (esc == '"') s += '"';
                else if (esc == '\\') s += '\\';
                else if (esc == '/') s += '/';
                else if (esc == 'b') s += '\b';
                else if (esc == 'f') s += '\f';
                else if (esc == 'n') s += '\n';
                else if (esc == 'r') s += '\r';
                else if (esc == 't') s += '\t';
                else if (esc == 'u' && pos + 4 <= src.size()) {
                    std::string hex_str = src.substr(pos, 4);
                    pos += 4;
                    try {
                        unsigned long code = std::stoul(hex_str, nullptr, 16);
                        if (code < 128) {
                            s += static_cast<char>(code);
                        } else if (code <= 0x7FF) {
                            s += static_cast<char>(0xC0 | ((code >> 6) & 0x1F));
                            s += static_cast<char>(0x80 | (code & 0x3F));
                        } else {
                            s += static_cast<char>(0xE0 | ((code >> 12) & 0x0F));
                            s += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
                            s += static_cast<char>(0x80 | (code & 0x3F));
                        }
                    } catch (...) {
                        s += '?';
                    }
                } else s += esc;
            } else {
                s += c;
            }
        }
        return Value(s);
    }

    Value parse_array() {
        pos++; // skip '['
        Value arr = Value::array();
        skip_whitespace();
        if (peek() == ']') {
            get();
            return arr;
        }
        while (pos < src.size()) {
            skip_whitespace();
            if (peek() == ']') {
                get();
                break;
            }
            arr.push_back(parse_value());
            skip_whitespace();
            char c = get();
            if (c == ']') break;
            if (c != ',') break;
        }
        return arr;
    }

    Value parse_object() {
        pos++; // skip '{'
        Value obj = Value::object();
        skip_whitespace();
        if (peek() == '}') {
            get();
            return obj;
        }
        while (pos < src.size()) {
            skip_whitespace();
            if (peek() == '}') {
                get();
                break;
            }
            if (peek() != '"') break;
            Value key_val = parse_string();
            skip_whitespace();
            if (get() != ':') break;
            Value val = parse_value();
            obj[key_val.as_string()] = val;
            skip_whitespace();
            char c = get();
            if (c == '}') break;
            if (c != ',') break;
        }
        return obj;
    }
};

inline Value parse(const std::string& str) {
    Parser p(str);
    return p.parse();
}

} // namespace json
