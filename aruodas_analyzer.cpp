#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

static std::string trim(std::string s) {
    auto issp = [](unsigned char c){ return std::isspace(c); };
    while (!s.empty() && issp((unsigned char)s.front())) s.erase(s.begin());
    while (!s.empty() && issp((unsigned char)s.back())) s.pop_back();
    return s;
}

static std::string norm_space(const std::string& in) {
    std::string s = in;
    for (char& c : s) {
        if (c == '\xa0') c = ' ';
    }
    std::string out;
    out.reserve(s.size());
    bool prev_sp = false;
    for (unsigned char c : s) {
        bool sp = std::isspace(c) != 0;
        if (sp) {
            if (!prev_sp) out.push_back(' ');
        } else {
            out.push_back((char)c);
        }
        prev_sp = sp;
    }
    return trim(out);
}

static std::vector<std::string> parse_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string cur;
    bool in_quotes = false;

    for (size_t i = 0; i < line.size(); ++i) {
        char c = line[i];
        if (in_quotes) {
            if (c == '"') {
                if (i + 1 < line.size() && line[i + 1] == '"') {
                    cur.push_back('"');
                    ++i;
                } else {
                    in_quotes = false;
                }
            } else {
                cur.push_back(c);
            }
        } else {
            if (c == '"') {
                in_quotes = true;
            } else if (c == ',') {
                fields.push_back(cur);
                cur.clear();
            } else if (c == '\r' || c == '\n') {
                // ignore
            } else {
                cur.push_back(c);
            }
        }
    }
    fields.push_back(cur);
    return fields;
}

static bool to_double(const std::string& s, double& out) {
    std::string t = trim(s);
    if (t.empty()) return false;
    try {
        out = std::stod(t);
        return true;
    } catch (...) {
        return false;
    }
}

static bool to_int(const std::string& s, int& out) {
    std::string t = trim(s);
    if (t.empty()) return false;
    try {
        out = (int)std::lround(std::stod(t));
        return true;
    } catch (...) {
        return false;
    }
}

static double median_inplace(std::vector<double>& v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    size_t n = v.size();
    if (n % 2 == 1) return v[n / 2];
    return (v[n / 2 - 1] + v[n / 2]) / 2.0;
}

struct Listing {
    std::string scraped_at;
    std::string url;
    int price_eur = 0;
    double eur_per_m2 = 0.0;
    int rooms = -1;
    double area_m2 = -1.0;
    int irengtas = 0;
    std::string location;
    std::string street;
};

struct Scored {
    double deal = 0.0;
    double street_median = 0.0;
    int street_n = 0;
    Listing it;
    std::string key;
};

static void write_top(const std::string& out_path, const std::vector<Scored>& top,
                      const std::string& market_csv, int min_street_n, bool street_only, int top_n) {
    std::ofstream f(out_path, std::ios::binary);
    if (!f) {
        std::cerr << "NEPAVYKO atidaryti out: " << out_path << "\n";
        return;
    }

    f << "TOP " << top_n << " pagal (gatvės medianinis €/m² iš kainos.csv) / (skelbimo €/m²)\n";
    f << "CSV: " << market_csv
      << " | min_gatves_n=" << min_street_n
      << " | key=" << (street_only ? "street" : "location+street") << "\n";
    f << "======================================================================\n\n";

    for (size_t i = 0; i < top.size(); ++i) {
        const auto& s = top[i];
        const auto& it = s.it;

        std::string rooms = (it.rooms >= 0) ? (std::to_string(it.rooms) + "k") : "k: n/a";
        std::string area = (it.area_m2 > 0) ? (std::to_string((int)std::lround(it.area_m2*10.0)/10.0) + " m²") : "m²: n/a";
        std::string ir = it.irengtas ? "įrengtas" : "neįrengtas";
        std::string price = it.price_eur > 0 ? (std::to_string(it.price_eur) + " €") : "kaina: n/a";

        f << "#" << (i + 1)
          << " deal=" << s.deal
          << "  gatvės_mediana=" << (int)std::lround(s.street_median) << " €/m² (n=" << s.street_n << ")"
          << "  skelbimas=" << (int)std::lround(it.eur_per_m2) << " €/m²\n";
        f << it.location << ", " << it.street << " | " << rooms << " | " << area << " | " << ir << " | " << price << "\n";
        f << it.url << "\n";
        f << "----------------------------------------------------------------------\n";
    }
}

int main(int argc, char** argv) {
    std::string market_csv = "kainos.csv";
    std::string out_txt = "deals_top3.txt";
    int min_street_n = 5;
    bool street_only = false;
    int top_n = 3;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--csv" && i + 1 < argc) market_csv = argv[++i];
        else if (a == "--out" && i + 1 < argc) out_txt = argv[++i];
        else if (a == "--min-street-n" && i + 1 < argc) min_street_n = std::max(1, std::atoi(argv[++i]));
        else if (a == "--street-only") street_only = true;
        else if (a == "--top" && i + 1 < argc) top_n = std::max(1, std::atoi(argv[++i]));
        else {
            std::cerr << "Nežinomas arg: " << a << "\n";
            return 2;
        }
    }

    std::ifstream mf(market_csv, std::ios::binary);
    if (!mf) {
        std::cerr << "NERASTAS market CSV: " << market_csv << "\n";
        return 3;
    }

    std::string header_line;
    if (!std::getline(mf, header_line)) {
        std::cerr << "Tuščias market CSV: " << market_csv << "\n";
        return 4;
    }

    auto header = parse_csv_line(header_line);
    std::unordered_map<std::string, int> idx;
    for (int i = 0; i < (int)header.size(); ++i) idx[trim(header[i])] = i;

    auto need = [&](const std::string& col)->int{
        auto it = idx.find(col);
        if (it == idx.end()) return -1;
        return it->second;
    };

    int i_eur = need("eur_per_m2");
    int i_loc = need("location");
    int i_st  = need("street");
    if (i_eur < 0 || i_loc < 0 || i_st < 0) {
        std::cerr << "Market CSV trūksta stulpelių (reikia eur_per_m2, location, street)\n";
        return 5;
    }

    std::unordered_map<std::string, std::vector<double>> by_key_vals;
    std::unordered_map<std::string, int> by_key_count;

    std::string line;
    long long market_rows = 0;
    while (std::getline(mf, line)) {
        if (trim(line).empty()) continue;
        auto flds = parse_csv_line(line);
        if ((int)flds.size() <= std::max({i_eur, i_loc, i_st})) continue;

        double eur = 0.0;
        if (!to_double(flds[i_eur], eur) || eur <= 0.0) continue;

        std::string loc = norm_space(flds[i_loc]);
        std::string st  = norm_space(flds[i_st]);
        if (st.empty()) continue;

        std::string key = street_only ? st : (loc + " | " + st);
        by_key_vals[key].push_back(eur);
        by_key_count[key] += 1;
        market_rows++;
    }

    std::unordered_map<std::string, double> key_median;
    std::unordered_map<std::string, int> key_n;
    key_median.reserve(by_key_vals.size());
    key_n.reserve(by_key_vals.size());

    for (auto& kv : by_key_vals) {
        const std::string& key = kv.first;
        auto& vals = kv.second;
        int n = (int)vals.size();
        if (n < min_street_n) continue;
        double med = median_inplace(vals);
        key_median[key] = med;
        key_n[key] = n;
    }

    std::cerr << "[C++] market rows=" << market_rows
              << " | streets_with_median=" << key_median.size()
              << " | min_street_n=" << min_street_n
              << " | top=" << top_n << "\n";

    std::string in_header_line;
    if (!std::getline(std::cin, in_header_line)) {
        std::cerr << "STDIN tuščias\n";
        return 6;
    }
    auto in_header = parse_csv_line(in_header_line);
    std::unordered_map<std::string, int> in_idx;
    for (int i = 0; i < (int)in_header.size(); ++i) in_idx[trim(in_header[i])] = i;

    auto in_need = [&](const std::string& col)->int{
        auto it = in_idx.find(col);
        if (it == in_idx.end()) return -1;
        return it->second;
    };

    int in_scr = in_need("scraped_at");
    int in_url = in_need("url");
    int in_price = in_need("price_eur");
    int in_eur = in_need("eur_per_m2");
    int in_rooms = in_need("rooms");
    int in_area = in_need("area_m2");
    int in_ir = in_need("irengtas");
    int in_loc = in_need("location");
    int in_st = in_need("street");

    if (in_url < 0 || in_eur < 0 || in_loc < 0 || in_st < 0) {
        std::cerr << "STDIN CSV trūksta stulpelių (reikia url, eur_per_m2, location, street)\n";
        return 7;
    }

    std::vector<Scored> best;
    best.reserve((size_t)top_n);

    auto push_best = [&](const Scored& s){
        best.push_back(s);
        std::sort(best.begin(), best.end(), [](const Scored& a, const Scored& b){ return a.deal > b.deal; });
        if ((int)best.size() > top_n) best.resize((size_t)top_n);
    };

    long long in_rows = 0;
    long long scored_rows = 0;

    while (std::getline(std::cin, line)) {
        if (trim(line).empty()) continue;
        auto flds = parse_csv_line(line);
        if ((int)flds.size() <= std::max({in_url, in_eur, in_loc, in_st})) continue;

        Listing it;
        it.scraped_at = (in_scr >= 0 && in_scr < (int)flds.size()) ? flds[in_scr] : "";
        it.url = flds[in_url];

        double eur = 0.0;
        if (!to_double(flds[in_eur], eur) || eur <= 0.0) continue;
        it.eur_per_m2 = eur;

        it.location = norm_space(flds[in_loc]);
        it.street = norm_space(flds[in_st]);
        if (it.street.empty()) { in_rows++; continue; }

        if (in_price >= 0 && in_price < (int)flds.size()) to_int(flds[in_price], it.price_eur);
        if (in_rooms >= 0 && in_rooms < (int)flds.size()) to_int(flds[in_rooms], it.rooms);
        if (in_area >= 0 && in_area < (int)flds.size()) to_double(flds[in_area], it.area_m2);
        if (in_ir >= 0 && in_ir < (int)flds.size()) to_int(flds[in_ir], it.irengtas);

        std::string key = street_only ? it.street : (it.location + " | " + it.street);
        auto km = key_median.find(key);
        if (km == key_median.end()) { in_rows++; continue; }

        double med = km->second;
        double deal = med / it.eur_per_m2;

        Scored s;
        s.deal = deal;
        s.street_median = med;
        s.street_n = key_n[key];
        s.it = it;
        s.key = key;

        push_best(s);
        scored_rows++;
        in_rows++;
    }

    if (best.empty()) {
        std::cerr << "[C++] Nėra TOP (trūksta medianų pagal min_street_n)\n";
        return 8;
    }

    write_top(out_txt, best, market_csv, min_street_n, street_only, top_n);
    std::cerr << "[C++] in_rows=" << in_rows << " | scored=" << scored_rows << " | wrote=" << out_txt << "\n";
    return 0;
}
