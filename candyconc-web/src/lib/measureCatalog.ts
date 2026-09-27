/**
 * measureCatalog — statischer Frontend-Spiegel des Backend-Methodenkatalogs
 * (candyconc.analysis_defaults.METHOD_META, Track T4).
 *
 * ZWECK: Die Mass-Picker zeigen Formel/Erklaerung/Referenz schon VOR der
 * ersten Analyse (es existiert kein Katalog-REST-Endpoint; der method-Block
 * jeder Analyse-Antwort bleibt die Server-Wahrheit und hat Vorrang, inkl.
 * Pair-Event-Overrides).
 *
 * GENERIERT aus METHOD_META — NICHT von Hand editieren. Der Kontrakt-Test
 * src/__tests__/lib/measureCatalogContract.test.ts pinnt jede Zeile
 * byte-identisch gegen die Backend-Felder.
 *
 * Regenerate with `scripts/generate_measure_catalog.py`. MEASURE_CATALOG is
 * the German rendering (backend default), MEASURE_CATALOG_EN the English one.
 */

import { currentLocale } from '@/i18n/locale'
import type { AppLocale } from '@/i18n'

export interface MeasureCatalogEntry {
  /** Menschlich lesbarer Name der Kennzahl (deutsches UI-Label). */
  name: string
  /** LaTeX-Formel der implementierten Berechnung (Backend-Wahrheit). */
  latex_formula: string
  /** Glaettungs-/Korrekturhinweis ('none' wenn exakt). */
  smoothing: string
  /** Feld, nach dem eine Standardsortierung absteigend ordnet. */
  sort_key: string
  /** Praesentations-MathML der Formel (nativ renderbar, keine Library). */
  formula_mathml: string
  /** Neutrale Lesehilfe (2-3 Saetze, inkl. bekannter Verzerrungen). */
  explanation: string
  /** Etablierte Quelle des Masses. */
  reference: string
}

// i18n-ignore-start: generated German and English renderings of METHOD_META
export const MEASURE_CATALOG: Record<string, MeasureCatalogEntry> = {
  "logdice": {
    "name": "logDice",
    "latex_formula": "14 + \\log_2\\!\\left(\\frac{2\\,O_{11}}{f_1 + f_2}\\right)",
    "smoothing": "none",
    "sort_key": "dice",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mn>14</mn><mo>+</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><mrow><mn>2</mn><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>f</mi><mn>1</mn></msub><mo>+</mo><msub><mi>f</mi><mn>2</mn></msub></mrow></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Dice-Koeffizient auf einer log2-Skala nach Rychlý 2008. Der Wert hängt nicht von der Korpusgröße ab, ist frequenzstabil und wird von seltenen Paaren kaum verzerrt. Rychlý gibt Orientierungspunkte: 14 erreicht ein Paar, dessen Wörter immer gemeinsam vorkommen, meist liegt der Wert unter 10, 0 heißt weniger als ein gemeinsames Vorkommen auf 16.000 Vorkommen eines der beiden Wörter, und negative Werte zeigen keine statistisch bedeutsame Kollokation. Ein Punkt mehr bedeutet doppelt so häufiges gemeinsames Vorkommen, sieben Punkte rund hundertmal so häufiges. Eine Schwelle für bemerkenswerte Kollokationen gibt Rychlý nicht an.",
    "reference": "Rychlý 2008"
  },
  "logdice_window": {
    "name": "logDice (Fenster-Randsummen)",
    "latex_formula": "14 + \\log_2\\!\\left(\\frac{2\\,O_{11}}{R_1 + C_1}\\right)",
    "smoothing": "none",
    "sort_key": "logdice_window",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mn>14</mn><mo>+</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><mrow><mn>2</mn><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>R</mi><mn>1</mn></msub><mo>+</mo><msub><mi>C</mi><mn>1</mn></msub></mrow></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Log-Transformation des Dice-Koeffizienten über die Randsummen der Distanztafel. Nicht über Knoten vergleichbar.",
    "reference": "Dice auf Evert 2004, Fig. 2.13"
  },
  "dice": {
    "name": "Dice",
    "latex_formula": "\\frac{2\\,O_{11}}{f_1 + f_2}",
    "smoothing": "none",
    "sort_key": "dice",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mn>2</mn><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>f</mi><mn>1</mn></msub><mo>+</mo><msub><mi>f</mi><mn>2</mn></msub></mrow></mfrac></math>",
    "explanation": "Harmonische Verrechnung der Kookkurrenzfrequenz mit den Randhäufigkeiten beider Ausdrücke, Wertebereich 0 bis 1. Das Maß ist symmetrisch; hohe Werte setzen voraus, dass beide Ausdrücke überwiegend gemeinsam auftreten.",
    "reference": "Dice 1945"
  },
  "mi": {
    "name": "Mutual Information (MI)",
    "latex_formula": "\\log_2\\!\\left(\\frac{O_{11}}{E_{11}}\\right),\\quad E_{11} = \\frac{R_1 \\cdot C_1}{N_\\Omega}",
    "smoothing": "none",
    "sort_key": "mi",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow><mo>,</mo><msub><mi>E</mi><mn>11</mn></msub><mo>=</mo><mfrac><mrow><msub><mi>R</mi><mn>1</mn></msub><mo>&#8901;</mo><msub><mi>C</mi><mn>1</mn></msub></mrow><msub><mi>N</mi><mi>&#937;</mi></msub></mfrac></math>",
    "explanation": "Vergleicht die beobachtete mit der bei Unabhängigkeit erwarteten Kookkurrenz auf log2-Skala. MI überschätzt seltene Paare systematisch: schon wenige gemeinsame Vorkommen zweier niederfrequenter Ausdrücke erzeugen hohe Werte.",
    "reference": "Church & Hanks 1990"
  },
  "mi3": {
    "name": "MI3 (kubische MI)",
    "latex_formula": "\\log_2\\!\\left(\\frac{O_{11}^{3}}{E_{11}}\\right)",
    "smoothing": "none",
    "sort_key": "mi3",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msup><mrow><msub><mi>O</mi><mn>11</mn></msub></mrow><mn>3</mn></msup><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Variante der MI mit kubierter beobachteter Kookkurrenz, gerechnet über exakt dasselbe O/E-Paar wie die MI. Die Kubierung dämpft die Verzerrung der MI zugunsten seltener Paare, sodass hohe Werte Assoziation und substanzielle Frequenz zugleich verlangen; eine Signifikanzaussage ist damit nicht verbunden.",
    "reference": "Oakes 1998"
  },
  "lmi": {
    "name": "Local MI (LMI)",
    "latex_formula": "O_{11} \\cdot \\log_2\\!\\left(\\frac{O_{11}}{E_{11}}\\right)",
    "smoothing": "none",
    "sort_key": "lmi",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>O</mi><mn>11</mn></msub><mo>&#8901;</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Gewichtet die MI mit der beobachteten Kookkurrenzfrequenz und gleicht deren Überschätzung seltener Paare teilweise aus. Im Gegenzug dominieren hochfrequente Kombinationen die Rangliste stärker.",
    "reference": "Evert 2005"
  },
  "npmi": {
    "name": "Normalized PMI",
    "latex_formula": "\\frac{\\log_2(O_{11}/E_{11})}{-\\log_2(O_{11}/N_\\Omega)}",
    "smoothing": "none",
    "sort_key": "npmi",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow></mrow><mrow><mo>&#8722;</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>N</mi><mi>&#937;</mi></msub></mfrac><mo>)</mo></mrow></mrow></mfrac></math>",
    "explanation": "Auf den Bereich −1 bis 1 normierte punktweise MI: 1 bedeutet perfekte Kookkurrenz, 0 Unabhängigkeit. Die Normierung erleichtert Vergleiche, ändert aber nichts an der Instabilität bei sehr kleinen Frequenzen.",
    "reference": "Bouma 2009"
  },
  "t": {
    "name": "t-Score",
    "latex_formula": "\\frac{O_{11} - E_{11}}{\\sqrt{O_{11}}}",
    "smoothing": "none",
    "sort_key": "t",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>&#8722;</mo><msub><mi>E</mi><mn>11</mn></msub></mrow><msqrt><msub><mi>O</mi><mn>11</mn></msub></msqrt></mfrac></math>",
    "explanation": "Prüfgröße für die Differenz zwischen beobachteter und erwarteter Kookkurrenz relativ zur Streuung der Beobachtung. Der t-Score bevorzugt hochfrequente Kollokationen; die zugrunde liegende Normalverteilungsannahme ist bei Korpusdaten nur näherungsweise erfüllt.",
    "reference": "Church et al. 1991"
  },
  "z": {
    "name": "z-Score",
    "latex_formula": "\\frac{O_{11} - E_{11}}{\\sqrt{E_{11}}}",
    "smoothing": "none",
    "sort_key": "z",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>&#8722;</mo><msub><mi>E</mi><mn>11</mn></msub></mrow><msqrt><msub><mi>E</mi><mn>11</mn></msub></msqrt></mfrac></math>",
    "explanation": "Standardisierte Abweichung der beobachteten von der erwarteten Kookkurrenz. Bei kleinen Erwartungswerten wird der z-Score stark aufgebläht und ist für seltene Kollokate entsprechend vorsichtig zu lesen.",
    "reference": "Berry-Rogghe 1973"
  },
  "chi2_cell": {
    "name": "Chi-square Zellbeitrag",
    "latex_formula": "\\frac{(O_{11} - E_{11})^2}{E_{11}}",
    "smoothing": "none",
    "sort_key": "chi2_cell",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msup><mrow><mo>(</mo><msub><mi>O</mi><mn>11</mn></msub><mo>&#8722;</mo><msub><mi>E</mi><mn>11</mn></msub><mo>)</mo></mrow><mn>2</mn></msup></mrow><msub><mi>E</mi><mn>11</mn></msub></mfrac></math>",
    "explanation": "Beitrag der Zelle (Knoten, Kollokat) zur Pearson-Chi-Quadrat-Statistik. Es handelt sich nur um eine der vier Zellen, nicht um den vollständigen Test; bei kleinen Erwartungswerten ist der Wert unzuverlässig.",
    "reference": "Pearson 1900"
  },
  "ll": {
    "name": "Log-Likelihood (G^2)",
    "latex_formula": "2 \\sum_{ij} O_{ij}\\,\\ln\\!\\left(\\frac{O_{ij}}{E_{ij}}\\right)",
    "smoothing": "none",
    "sort_key": "ll",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mn>2</mn><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mi>ln</mi><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Dunnings Log-Likelihood-Statistik (G²) über die vollständige 2x2-Kontingenztafel; auch bei kleinen Frequenzen robuster als Chi-Quadrat. G² misst Signifikanz, nicht Effektstärke: in großen Korpora werden auch triviale Unterschiede hochsignifikant.",
    "reference": "Dunning 1993"
  },
  "delta_p_nc": {
    "name": "Delta-P (Knoten -> Kollokat)",
    "latex_formula": "\\Delta P_{n\\to c} = P(c \\mid n) - P(c \\mid \\lnot n) = \\frac{O_{11}}{R_1} - \\frac{C_1 - O_{11}}{N_\\Omega - R_1}",
    "smoothing": "none",
    "sort_key": "delta_p_nc",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>&#916;</mi><mrow><mi>n</mi><mo>&#8594;</mo><mi>c</mi></mrow></msub><mi>P</mi><mo>=</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>R</mi><mn>1</mn></msub></mfrac><mo>&#8722;</mo><mfrac><mrow><msub><mi>C</mi><mn>1</mn></msub><mo>&#8722;</mo><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>N</mi><mi>&#937;</mi></msub><mo>&#8722;</mo><msub><mi>R</mi><mn>1</mn></msub></mrow></mfrac></math>",
    "explanation": "Asymmetrisches Assoziationsmaß: Differenz der Wahrscheinlichkeit des Kollokats mit und ohne Knoten, Wertebereich −1 bis 1. Erfasst Richtungseffekte, die symmetrische Maße wie MI oder Dice verdecken.",
    "reference": "Allan 1980; Ellis 2006; Gries 2013"
  },
  "delta_p_cn": {
    "name": "Delta-P (Kollokat -> Knoten)",
    "latex_formula": "\\Delta P_{c\\to n} = P(n \\mid c) - P(n \\mid \\lnot c) = \\frac{O_{11}}{C_1} - \\frac{R_1 - O_{11}}{N_\\Omega - C_1}",
    "smoothing": "none",
    "sort_key": "delta_p_cn",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>&#916;</mi><mrow><mi>c</mi><mo>&#8594;</mo><mi>n</mi></mrow></msub><mi>P</mi><mo>=</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>C</mi><mn>1</mn></msub></mfrac><mo>&#8722;</mo><mfrac><mrow><msub><mi>R</mi><mn>1</mn></msub><mo>&#8722;</mo><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>N</mi><mi>&#937;</mi></msub><mo>&#8722;</mo><msub><mi>C</mi><mn>1</mn></msub></mrow></mfrac></math>",
    "explanation": "Gegenrichtung des Delta-P: Differenz der Wahrscheinlichkeit des Knotens mit und ohne Kollokat, Wertebereich −1 bis 1. Zusammen mit der Hinrichtung zeigt es, welcher Partner den anderen stärker vorhersagt.",
    "reference": "Allan 1980; Ellis 2006; Gries 2013"
  },
  "chi2": {
    "name": "Chi-square (2x2 Pearson, df=1)",
    "latex_formula": "\\chi^2 = \\sum_{ij} \\frac{(O_{ij} - E_{ij})^2}{E_{ij}},\\quad E_{ij} = \\frac{\\text{row}_i \\cdot \\text{col}_j}{N}",
    "smoothing": "none",
    "sort_key": "chi2",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msup><mi>&#967;</mi><mn>2</mn></msup><mo>=</mo><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><mfrac><mrow><msup><mrow><mo>(</mo><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>&#8722;</mo><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>)</mo></mrow><mn>2</mn></msup></mrow><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac></math>",
    "explanation": "Pearsons Chi-Quadrat-Test über die vollständige 2x2-Tafel (df=1). Reines Signifikanzmaß ohne Effektstärke; bei erwarteten Zellbesetzungen unter 5 ist die Approximation unzuverlässig (siehe expected_min).",
    "reference": "Pearson 1900"
  },
  "chi2_signed": {
    "name": "Signiertes Chi-square (2x2 Pearson)",
    "latex_formula": "\\operatorname{sign}(\\Delta_{pm}) \\cdot \\sum_{ij} \\frac{(O_{ij} - E_{ij})^2}{E_{ij}}",
    "smoothing": "none",
    "sort_key": "chi2_signed",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>sign</mi><mrow><mo>(</mo><msub><mi>&#916;</mi><mrow><mi>p</mi><mi>m</mi></mrow></msub><mo>)</mo></mrow><mo>&#8901;</mo><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><mfrac><mrow><msup><mrow><mo>(</mo><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>&#8722;</mo><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>)</mo></mrow><mn>2</mn></msup></mrow><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac></math>",
    "explanation": "Chi-Quadrat mit dem Vorzeichen der Frequenzdifferenz: positive Werte zeigen Überrepräsentation im Zielkorpus, negative im Referenzkorpus. Der Betrag ist wie chi2 zu lesen (Signifikanz, keine Effektstärke).",
    "reference": "Pearson 1900"
  },
  "ll_signed": {
    "name": "Signiertes Log-Likelihood",
    "latex_formula": "\\operatorname{sign}(\\Delta_{pm}) \\cdot 2 \\sum_{ij} O_{ij}\\,\\ln\\!\\left(\\frac{O_{ij}}{E_{ij}}\\right)",
    "smoothing": "none",
    "sort_key": "ll_signed",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>sign</mi><mrow><mo>(</mo><msub><mi>&#916;</mi><mrow><mi>p</mi><mi>m</mi></mrow></msub><mo>)</mo></mrow><mo>&#8901;</mo><mn>2</mn><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mi>ln</mi><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "G² mit dem Vorzeichen der Frequenzdifferenz: positive Werte bedeuten Überrepräsentation im Zielkorpus, negative im Referenzkorpus. Wie das ungerichtete G² eine Signifikanz-, keine Effektstärkeaussage.",
    "reference": "Dunning 1993"
  },
  "log_ratio": {
    "name": "Log Ratio (Hardie)",
    "latex_formula": "\\log_2\\!\\left(\\frac{(O_{11}+0.5)/N_t}{(O_{21}+0.5)/N_r}\\right)",
    "smoothing": "Haldane-Anscombe +0.5",
    "sort_key": "log_ratio",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><mrow><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>+</mo><mn>0.5</mn></mrow><msub><mi>N</mi><mi>t</mi></msub></mfrac></mrow><mrow><mfrac><mrow><msub><mi>O</mi><mn>21</mn></msub><mo>+</mo><mn>0.5</mn></mrow><msub><mi>N</mi><mi>r</mi></msub></mfrac></mrow></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Binärer Logarithmus des Verhältnisses der relativen Häufigkeiten (Effektstärke): +1 entspricht doppelter Häufigkeit im Zielkorpus. Log Ratio trifft keine Signifikanzaussage und wird deshalb mit einem Signifikanzmaß (G², BIC) kombiniert; die +0.5-Glättung hält einseitige Nullzellen endlich.",
    "reference": "Hardie 2014"
  },
  "lrc": {
    "name": "Konservatives Log Ratio (Evert 2022)",
    "latex_formula": "\\mathrm{LRC} = \\operatorname{sign}(\\widehat{LR}) \\cdot \\max\\left(0, \\left|\\text{nullnahe Grenze von }\\mathrm{KI}_{1-\\alpha}(LR)\\right|\\right)",
    "smoothing": "none",
    "sort_key": "lrc",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>LRC</mi><mo>=</mo><mi>sgn</mi><mo>(</mo><msub><mi>LR</mi><mn>0</mn></msub><mo>)</mo><mo>&#183;</mo><mi>min</mi><mrow><mo>|</mo><msub><mi>log</mi><mn>2</mn></msub><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>/</mo><msub><mi>R</mi><mn>1</mn></msub></mrow><mrow><msub><mi>O</mi><mn>21</mn></msub><mo>/</mo><mo>(</mo><mi>N</mi><mo>-</mo><msub><mi>R</mi><mn>1</mn></msub><mo>)</mo></mrow></mfrac><mo>|</mo></mrow></math>",
    "explanation": "Konservatives Log Ratio: die Grenze des Konfidenzintervalls für das Log Ratio, die NÄHER AN NULL liegt, also die kleinste Effektstärke, die mit den Daten verträglich ist. Schließt das Intervall die Null ein, ist der Effekt nicht von Null zu trennen und der LRC ist 0. Genau deshalb spült er seltene Kandidaten nicht nach oben: ein einzelnes Vorkommen erzeugt ein weites Intervall und damit einen LRC von 0. Das Intervall ist EXAKT und bedingt auf die Randsumme (Clopper-Pearson), keine Normalnäherung. Die Bonferroni-Korrektur läuft über die Zahl der gleichzeitig geprüften Kandidaten (lrc_tests im Methodenblock), das Niveau ist lrc_alpha. Auf der Kollokationsfläche sind die Randsummen Everts Distanztafel: Zielrate O11/|W(u)|, Referenzrate (f(v)-O11)/(N-|W(u)|). In der Keyness vergleicht es Ziel und Referenz: a/N_t gegen c/N_r.",
    "reference": "Evert 2022; Clopper & Pearson 1934"
  },
  "bic": {
    "name": "Bayes Information Criterion",
    "latex_formula": "G^2 - \\ln(N_t + N_r)",
    "smoothing": "none",
    "sort_key": "bic",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msup><mi>G</mi><mn>2</mn></msup><mo>&#8722;</mo><mi>ln</mi><mrow><mo>(</mo><msub><mi>N</mi><mi>t</mi></msub><mo>+</mo><msub><mi>N</mi><mi>r</mi></msub><mo>)</mo></mrow></math>",
    "explanation": "Bayessches Informationskriterium als Approximation aus G²: Werte über etwa 2 gelten als positive, über etwa 10 als sehr starke Evidenz gegen Unabhängigkeit. Anders als der p-Wert bestraft das BIC die Korpusgröße und läuft in großen Korpora nicht automatisch ins Signifikante.",
    "reference": "Wilson 2013"
  },
  "p_value": {
    "name": "p-Wert (Chi-square, df=1)",
    "latex_formula": "P(\\chi^2_1 \\ge G^2)",
    "smoothing": "none",
    "sort_key": "p_value",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>P</mi><mrow><mo>(</mo><msubsup><mi>&#967;</mi><mn>1</mn><mn>2</mn></msubsup><mo>&#8805;</mo><msup><mi>G</mi><mn>2</mn></msup><mo>)</mo></mrow></math>",
    "explanation": "Wahrscheinlichkeit, unter der Nullhypothese der Unabhängigkeit einen mindestens so großen G²-Wert zu beobachten (Chi-Quadrat-Verteilung, df=1). Bei vielen parallelen Tests ist der rohe p-Wert ohne Korrektur irreführend (siehe q-Wert).",
    "reference": "Dunning 1993"
  },
  "q_value": {
    "name": "q-Wert (FDR, Benjamini-Hochberg)",
    "latex_formula": "q_{(i)} = \\min_{k \\ge i}\\ \\frac{m \\cdot p_{(k)}}{k}",
    "smoothing": "none",
    "sort_key": "q_value",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>q</mi><mrow><mo>(</mo><mi>i</mi><mo>)</mo></mrow></msub><mo>=</mo><munder><mi>min</mi><mrow><mi>k</mi><mo>&#8805;</mo><mi>i</mi></mrow></munder><mfrac><mrow><mi>m</mi><mo>&#8901;</mo><msub><mi>p</mi><mrow><mo>(</mo><mi>k</mi><mo>)</mo></mrow></msub></mrow><mi>k</mi></mfrac></math>",
    "explanation": "Benjamini-Hochberg-adjustierter p-Wert: kontrolliert die erwartete Falscherkennungsrate (FDR) über alle gleichzeitig getesteten Ausdrücke. Für Keyword-Listen mit vielen Tests dem rohen p-Wert vorzuziehen.",
    "reference": "Benjamini & Hochberg 1995"
  },
  "diff_per_million": {
    "name": "Differenz pro Million",
    "latex_formula": "\\frac{O_{11}}{N_t}\\cdot 10^6 - \\frac{O_{21}}{N_r}\\cdot 10^6",
    "smoothing": "none",
    "sort_key": "diff_per_million",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>N</mi><mi>t</mi></msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup><mo>&#8722;</mo><mfrac><msub><mi>O</mi><mn>21</mn></msub><msub><mi>N</mi><mi>r</mi></msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup></math>",
    "explanation": "Differenz der auf eine Million Tokens normalisierten Häufigkeiten zwischen Ziel- und Referenzkorpus. Deskriptives Maß ohne Signifikanzaussage; der Absolutwert hängt stark von der Grundfrequenz des Ausdrucks ab.",
    "reference": "Brezina 2018"
  },
  "expected_min": {
    "name": "Kleinste erwartete Zellbesetzung E_min",
    "latex_formula": "E_{\\min} = \\min_{ij} E_{ij},\\quad E_{ij} = \\frac{\\text{row}_i \\cdot \\text{col}_j}{N}",
    "smoothing": "none",
    "sort_key": "expected_min",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>E</mi><mi>min</mi></msub><mo>=</mo><munder><mi>min</mi><mrow><mi>i</mi><mi>j</mi></mrow></munder><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></math>",
    "explanation": "Kleinste erwartete Zellbesetzung der 2x2-Tafel. Diagnostik für die Gültigkeit der asymptotischen Tests: liegt sie unter 5, ist die Chi-Quadrat-Approximation unzuverlässig.",
    "reference": "Cochran 1954"
  },
  "low_reliability": {
    "name": "Geringe Zuverlaessigkeit (E_min < 5)",
    "latex_formula": "\\mathbb{1}\\!\\left[E_{\\min} < 5\\right]",
    "smoothing": "none",
    "sort_key": "low_reliability",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>&#120793;</mi><mrow><mo>[</mo><msub><mi>E</mi><mi>min</mi></msub><mo>&lt;</mo><mn>5</mn><mo>]</mo></mrow></math>",
    "explanation": "Markierung, dass mindestens eine erwartete Zellbesetzung unter 5 liegt. Die asymptotischen Teststatistiken (chi2, G²) sind für solche Zeilen nur eingeschränkt belastbar.",
    "reference": "Cochran 1954"
  },
  "frequency": {
    "name": "Frequenz",
    "latex_formula": "f = \\#\\{\\text{Vorkommen}\\}",
    "smoothing": "none",
    "sort_key": "freq",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>f</mi><mo>=</mo><mo>#</mo><mrow><mo>{</mo><mtext>Vorkommen</mtext><mo>}</mo></mrow></math>",
    "explanation": "Absolute Vorkommenshäufigkeit im gewählten Geltungsbereich. Für Vergleiche zwischen unterschiedlich großen Korpora oder Teilkorpora sind normalisierte Häufigkeiten (pro Million) erforderlich.",
    "reference": "Brezina 2018"
  },
  "ttr": {
    "name": "Type-Token Ratio",
    "latex_formula": "\\mathrm{TTR} = \\frac{V}{N}",
    "smoothing": "none",
    "sort_key": "ttr",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mi>V</mi><mi>N</mi></mfrac></math>",
    "explanation": "Verhältnis der Typen (V) zur Tokenzahl (N) als Maß lexikalischer Vielfalt. Stark textlängenabhängig: längere Texte erhalten systematisch niedrigere Werte, direkte Vergleiche verlangen gleiche Längen oder standardisierte Varianten (STTR, MATTR).",
    "reference": "Brezina 2018"
  },
  "sttr": {
    "name": "Standardised TTR",
    "latex_formula": "\\mathrm{STTR} = \\frac{1}{W}\\sum_{w=1}^{W} \\frac{V_w}{n}\\quad (n = \\text{Fenstergröße})",
    "smoothing": "none",
    "sort_key": "sttr",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mn>1</mn><mi>W</mi></mfrac><munderover><mo>&#8721;</mo><mrow><mi>w</mi><mo>=</mo><mn>1</mn></mrow><mi>W</mi></munderover><mfrac><msub><mi>V</mi><mi>w</mi></msub><mi>n</mi></mfrac></math>",
    "explanation": "Mittlere TTR über aufeinanderfolgende, gleich große Textfenster; neutralisiert die Längenabhängigkeit der rohen TTR. Restfenster unterhalb der Fenstergröße bleiben unberücksichtigt.",
    "reference": "Scott, WordSmith Tools"
  },
  "guiraud": {
    "name": "Guiraud's R",
    "latex_formula": "R = \\frac{V}{\\sqrt{N}}",
    "smoothing": "none",
    "sort_key": "guiraud",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mi>V</mi><msqrt><mi>N</mi></msqrt></mfrac></math>",
    "explanation": "Wurzeltransformierte Type-Token-Relation (V/√N). Mildert die Längenabhängigkeit der TTR ab, beseitigt sie aber nicht vollständig.",
    "reference": "Guiraud 1954"
  },
  "mattr": {
    "name": "Moving-Average TTR",
    "latex_formula": "\\mathrm{MATTR} = \\frac{1}{N - n + 1}\\sum_{i=1}^{N-n+1}\\frac{V_i}{n}",
    "smoothing": "none",
    "sort_key": "mattr",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mn>1</mn><mrow><mi>N</mi><mo>&#8722;</mo><mi>n</mi><mo>+</mo><mn>1</mn></mrow></mfrac><munderover><mo>&#8721;</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mrow><mi>N</mi><mo>&#8722;</mo><mi>n</mi><mo>+</mo><mn>1</mn></mrow></munderover><mfrac><msub><mi>V</mi><mi>i</mi></msub><mi>n</mi></mfrac></math>",
    "explanation": "TTR über ein gleitendes Fenster fester Länge, über alle Fensterpositionen gemittelt. Weitgehend längenunabhängig und feiner aufgelöst als die fensterblockweise STTR.",
    "reference": "Covington & McFall 2010"
  },
  "dp": {
    "name": "Gries DP (Deviation of Proportions)",
    "latex_formula": "\\mathrm{DP} = \\tfrac{1}{2}\\sum_i\\left|\\frac{o_i}{F} - \\frac{s_i}{N}\\right|",
    "smoothing": "none",
    "sort_key": "dp",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mn>1</mn><mn>2</mn></mfrac><munder><mo>&#8721;</mo><mi>i</mi></munder><mrow><mo>|</mo><mfrac><msub><mi>o</mi><mi>i</mi></msub><mi>F</mi></mfrac><mo>&#8722;</mo><mfrac><msub><mi>s</mi><mi>i</mi></msub><mi>N</mi></mfrac><mo>|</mo></mrow></math>",
    "explanation": "Abweichung der beobachteten Trefferanteile von den nach Dokumentgröße erwarteten Anteilen: 0 bedeutet gleichmäßige Verteilung, Werte gegen 1 Konzentration auf wenige Dokumente. Ergänzt Frequenzmaße, die solche Klumpung verdecken.",
    "reference": "Gries 2008"
  },
  "dpnorm": {
    "name": "Gries DPnorm (normalisiert)",
    "latex_formula": "\\mathrm{DP_{norm}} = \\frac{\\mathrm{DP}}{1 - \\min_i (s_i / N)}",
    "smoothing": "none",
    "sort_key": "dpnorm",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mi>DP</mi><mrow><mn>1</mn><mo>&#8722;</mo><munder><mi>min</mi><mi>i</mi></munder><mrow><mo>(</mo><mfrac><msub><mi>s</mi><mi>i</mi></msub><mi>N</mi></mfrac><mo>)</mo></mrow></mrow></mfrac></math>",
    "explanation": "Auf den erreichbaren Maximalwert normierte DP. Dadurch zwischen Korpora mit unterschiedlich vielen und unterschiedlich großen Teilen vergleichbar.",
    "reference": "Lijffijt & Gries 2012"
  },
  "juilland_d": {
    "name": "Juilland's D",
    "latex_formula": "D = 1 - \\frac{\\mathrm{VC}}{\\sqrt{n - 1}},\\quad \\mathrm{VC} = \\frac{\\sigma(v_i)}{\\bar{v}},\\ v_i = \\frac{o_i}{s_i}",
    "smoothing": "none",
    "sort_key": "juilland_d",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>D</mi><mo>=</mo><mn>1</mn><mo>&#8722;</mo><mfrac><mi>VC</mi><msqrt><mrow><mi>n</mi><mo>&#8722;</mo><mn>1</mn></mrow></msqrt></mfrac></math>",
    "explanation": "Klassisches Dispersionsmaß auf Basis des Variationskoeffizienten der größennormalisierten Teilfrequenzen; 1 bedeutet perfekt gleichmäßige Verteilung. Bei vielen kleinen Teilen neigt D dazu, Gleichmäßigkeit zu überschätzen.",
    "reference": "Juilland & Chang-Rodríguez 1964"
  },
  "carroll_d2": {
    "name": "Carroll's D2 (normalisierte Entropie)",
    "latex_formula": "D_2 = \\frac{H}{\\ln n},\\quad H = -\\sum_i p_i \\ln p_i,\\ p_i = \\frac{o_i}{F}",
    "smoothing": "none",
    "sort_key": "carroll_d2",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>D</mi><mn>2</mn></msub><mo>=</mo><mfrac><mi>H</mi><mrow><mi>ln</mi><mi>n</mi></mrow></mfrac><mo>,</mo><mi>H</mi><mo>=</mo><mo>&#8722;</mo><munder><mo>&#8721;</mo><mi>i</mi></munder><msub><mi>p</mi><mi>i</mi></msub><mi>ln</mi><msub><mi>p</mi><mi>i</mi></msub></math>",
    "explanation": "Normierte Entropie der Trefferverteilung über die Teile: 1 bedeutet Gleichverteilung, 0 vollständige Konzentration auf einen Teil. Berücksichtigt anders als Range auch die Frequenzanteile.",
    "reference": "Carroll 1970"
  },
  "range_prop": {
    "name": "Range (Anteil erreichter Teile)",
    "latex_formula": "\\mathrm{Range} = \\frac{\\#\\{i : o_i > 0\\}}{n}",
    "smoothing": "none",
    "sort_key": "range_prop",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mo>#</mo><mrow><mo>{</mo><mi>i</mi><mo>:</mo><msub><mi>o</mi><mi>i</mi></msub><mo>&gt;</mo><mn>0</mn><mo>}</mo></mrow></mrow><mi>n</mi></mfrac></math>",
    "explanation": "Anteil der Teile (Dokumente), in denen der Ausdruck mindestens einmal vorkommt. Robustes, aber grobes Streuungsmaß: Frequenzunterschiede innerhalb der Teile bleiben unberücksichtigt.",
    "reference": "Brezina 2018"
  },
  "vc": {
    "name": "Variationskoeffizient (VC)",
    "latex_formula": "\\mathrm{VC} = \\frac{\\sigma(v_i)}{\\bar{v}},\\ v_i = \\frac{o_i}{s_i}",
    "smoothing": "none",
    "sort_key": "vc",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mi>&#963;</mi><mrow><mo>(</mo><msub><mi>v</mi><mi>i</mi></msub><mo>)</mo></mrow></mrow><mover><mi>v</mi><mo>&#175;</mo></mover></mfrac><mo>,</mo><msub><mi>v</mi><mi>i</mi></msub><mo>=</mo><mfrac><msub><mi>o</mi><mi>i</mi></msub><msub><mi>s</mi><mi>i</mi></msub></mfrac></math>",
    "explanation": "Variationskoeffizient der größennormalisierten Teilfrequenzen; Grundbaustein von Juillands D. Höhere Werte bedeuten ungleichmäßigere Verteilung über die Teile.",
    "reference": "Juilland & Chang-Rodríguez 1964"
  },
  "per_million": {
    "name": "Treffer pro Million (Periode)",
    "latex_formula": "\\mathrm{pM} = \\frac{h_p}{n_p}\\cdot 10^{6}",
    "smoothing": "none",
    "sort_key": "per_million",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><msub><mi>h</mi><mi>p</mi></msub><msub><mi>n</mi><mi>p</mi></msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup></math>",
    "explanation": "Normalisierte Häufigkeit je Periode: Treffer pro Million laufender Tokens. Macht Perioden mit unterschiedlicher Textmenge vergleichbar; bei kleinen Perioden-Token-Zahlen schwankt der Wert stark (siehe Konfidenzintervall).",
    "reference": "Brezina 2018"
  },
  "wilson_ci": {
    "name": "Wilson-Konfidenzintervall (95%)",
    "latex_formula": "\\frac{\\hat p + \\frac{z^2}{2n} \\pm z\\sqrt{\\frac{\\hat p(1-\\hat p)}{n} + \\frac{z^2}{4n^2}}}{1 + \\frac{z^2}{n}},\\quad \\hat p = \\frac{h_p}{n_p},\\ z = 1{,}96",
    "smoothing": "none",
    "sort_key": "per_million",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mover><mi>p</mi><mo>^</mo></mover><mo>+</mo><mfrac><msup><mi>z</mi><mn>2</mn></msup><mrow><mn>2</mn><mi>n</mi></mrow></mfrac><mo>&#177;</mo><mi>z</mi><msqrt><mrow><mfrac><mrow><mover><mi>p</mi><mo>^</mo></mover><mrow><mo>(</mo><mn>1</mn><mo>&#8722;</mo><mover><mi>p</mi><mo>^</mo></mover><mo>)</mo></mrow></mrow><mi>n</mi></mfrac><mo>+</mo><mfrac><msup><mi>z</mi><mn>2</mn></msup><mrow><mn>4</mn><msup><mi>n</mi><mn>2</mn></msup></mrow></mfrac></mrow></msqrt></mrow><mrow><mn>1</mn><mo>+</mo><mfrac><msup><mi>z</mi><mn>2</mn></msup><mi>n</mi></mfrac></mrow></mfrac></math>",
    "explanation": "95%-Konfidenzintervall (Wilson-Score) für die Token-Rate einer Periode, auf pro Million skaliert. Das Intervall ist asymmetrisch und auch bei null Treffern definiert (Untergrenze 0); enge Intervalle erfordern große Token-Zahlen je Periode.",
    "reference": "Wilson 1927"
  },
  "random_sample": {
    "name": "Uniforme Zufallsstichprobe (Thinning)",
    "latex_formula": "S \\subseteq \\{1,\\dots,N\\},\\ |S| = k = \\min(\\mathrm{sample},\\,N),\\quad P(i \\in S) = \\frac{k}{N}",
    "smoothing": "none",
    "sort_key": "pos",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>P</mi><mrow><mo>(</mo><mi>i</mi><mo>&#8712;</mo><mi>S</mi><mo>)</mo></mrow><mo>=</mo><mfrac><mi>k</mi><mi>N</mi></mfrac><mo>,</mo><mi>k</mi><mo>=</mo><mi>min</mi><mrow><mo>(</mo><mtext>sample</mtext><mo>,</mo><mi>N</mi><mo>)</mo></mrow></math>",
    "explanation": "Uniforme Zufallsstichprobe ohne Zurücklegen aus der Gesamttreffermenge, über den angegebenen Seed deterministisch reproduzierbar. Statistiken über die Stichprobe schätzen die Vollmenge nur mit Stichprobenfehler; die Provenienz (requested, drawn, seed, population) wird mitgeliefert.",
    "reference": "Brezina 2018"
  },
}

export const MEASURE_CATALOG_EN: Record<string, MeasureCatalogEntry> = {
  "logdice": {
    "name": "logDice",
    "latex_formula": "14 + \\log_2\\!\\left(\\frac{2\\,O_{11}}{f_1 + f_2}\\right)",
    "smoothing": "none",
    "sort_key": "dice",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mn>14</mn><mo>+</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><mrow><mn>2</mn><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>f</mi><mn>1</mn></msub><mo>+</mo><msub><mi>f</mi><mn>2</mn></msub></mrow></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Dice coefficient on a log2 scale after Rychlý 2008. The value does not depend on corpus size, is stable across frequencies and is hardly distorted by rare pairs. Rychlý gives orientation points: a pair whose words always occur together reaches 14, values are usually below 10, 0 means less than one co-occurrence per 16,000 occurrences of either word, and negative values show no statistically significant collocation. One point more means co-occurrence twice as frequent, seven points roughly a hundred times as frequent. Rychlý gives no threshold for notable collocations.",
    "reference": "Rychlý 2008"
  },
  "logdice_window": {
    "name": "logDice (window marginals)",
    "latex_formula": "14 + \\log_2\\!\\left(\\frac{2\\,O_{11}}{R_1 + C_1}\\right)",
    "smoothing": "none",
    "sort_key": "logdice_window",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mn>14</mn><mo>+</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><mrow><mn>2</mn><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>R</mi><mn>1</mn></msub><mo>+</mo><msub><mi>C</mi><mn>1</mn></msub></mrow></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Log transform of the Dice coefficient over the marginal totals of the distance table. Not comparable across nodes.",
    "reference": "Dice on Evert 2004, Fig. 2.13"
  },
  "dice": {
    "name": "Dice",
    "latex_formula": "\\frac{2\\,O_{11}}{f_1 + f_2}",
    "smoothing": "none",
    "sort_key": "dice",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mn>2</mn><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>f</mi><mn>1</mn></msub><mo>+</mo><msub><mi>f</mi><mn>2</mn></msub></mrow></mfrac></math>",
    "explanation": "Harmonic combination of the co-occurrence frequency with the marginal frequencies of both expressions, range 0 to 1. The measure is symmetric. High values require that both expressions mostly occur together.",
    "reference": "Dice 1945"
  },
  "mi": {
    "name": "Mutual Information (MI)",
    "latex_formula": "\\log_2\\!\\left(\\frac{O_{11}}{E_{11}}\\right),\\quad E_{11} = \\frac{R_1 \\cdot C_1}{N_\\Omega}",
    "smoothing": "none",
    "sort_key": "mi",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow><mo>,</mo><msub><mi>E</mi><mn>11</mn></msub><mo>=</mo><mfrac><mrow><msub><mi>R</mi><mn>1</mn></msub><mo>&#8901;</mo><msub><mi>C</mi><mn>1</mn></msub></mrow><msub><mi>N</mi><mi>&#937;</mi></msub></mfrac></math>",
    "explanation": "Compares the observed co-occurrence with the co-occurrence expected under independence on a log2 scale. MI systematically overrates rare pairs: a few joint occurrences of two low-frequency expressions already produce high values.",
    "reference": "Church & Hanks 1990"
  },
  "mi3": {
    "name": "MI3 (cubic MI)",
    "latex_formula": "\\log_2\\!\\left(\\frac{O_{11}^{3}}{E_{11}}\\right)",
    "smoothing": "none",
    "sort_key": "mi3",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msup><mrow><msub><mi>O</mi><mn>11</mn></msub></mrow><mn>3</mn></msup><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Variant of MI with the observed co-occurrence cubed, computed over exactly the same O/E pair as MI. Cubing dampens the bias of MI towards rare pairs, so high values require both association and substantial frequency. It makes no statement about significance.",
    "reference": "Oakes 1998"
  },
  "lmi": {
    "name": "Local MI (LMI)",
    "latex_formula": "O_{11} \\cdot \\log_2\\!\\left(\\frac{O_{11}}{E_{11}}\\right)",
    "smoothing": "none",
    "sort_key": "lmi",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>O</mi><mn>11</mn></msub><mo>&#8901;</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Weights MI by the observed co-occurrence frequency and partly offsets its overrating of rare pairs. In return, high-frequency combinations dominate the ranking more strongly.",
    "reference": "Evert 2005"
  },
  "npmi": {
    "name": "Normalized PMI",
    "latex_formula": "\\frac{\\log_2(O_{11}/E_{11})}{-\\log_2(O_{11}/N_\\Omega)}",
    "smoothing": "none",
    "sort_key": "npmi",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>E</mi><mn>11</mn></msub></mfrac><mo>)</mo></mrow></mrow><mrow><mo>&#8722;</mo><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>N</mi><mi>&#937;</mi></msub></mfrac><mo>)</mo></mrow></mrow></mfrac></math>",
    "explanation": "Pointwise MI normalized to the range −1 to 1: 1 means perfect co-occurrence, 0 independence. The normalization makes comparisons easier but does not change the instability at very small frequencies.",
    "reference": "Bouma 2009"
  },
  "t": {
    "name": "t-score",
    "latex_formula": "\\frac{O_{11} - E_{11}}{\\sqrt{O_{11}}}",
    "smoothing": "none",
    "sort_key": "t",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>&#8722;</mo><msub><mi>E</mi><mn>11</mn></msub></mrow><msqrt><msub><mi>O</mi><mn>11</mn></msub></msqrt></mfrac></math>",
    "explanation": "Test statistic for the difference between observed and expected co-occurrence relative to the variability of the observation. The t-score favors high-frequency collocations. The underlying normality assumption holds only approximately for corpus data.",
    "reference": "Church et al. 1991"
  },
  "z": {
    "name": "z-score",
    "latex_formula": "\\frac{O_{11} - E_{11}}{\\sqrt{E_{11}}}",
    "smoothing": "none",
    "sort_key": "z",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>&#8722;</mo><msub><mi>E</mi><mn>11</mn></msub></mrow><msqrt><msub><mi>E</mi><mn>11</mn></msub></msqrt></mfrac></math>",
    "explanation": "Standardized deviation of the observed from the expected co-occurrence. With small expected values the z-score is strongly inflated and should be read with corresponding caution for rare collocates.",
    "reference": "Berry-Rogghe 1973"
  },
  "chi2_cell": {
    "name": "Chi-square cell contribution",
    "latex_formula": "\\frac{(O_{11} - E_{11})^2}{E_{11}}",
    "smoothing": "none",
    "sort_key": "chi2_cell",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><msup><mrow><mo>(</mo><msub><mi>O</mi><mn>11</mn></msub><mo>&#8722;</mo><msub><mi>E</mi><mn>11</mn></msub><mo>)</mo></mrow><mn>2</mn></msup></mrow><msub><mi>E</mi><mn>11</mn></msub></mfrac></math>",
    "explanation": "Contribution of the cell (node, collocate) to the Pearson chi-square statistic. It is only one of the four cells, not the complete test. With small expected values the value is unreliable.",
    "reference": "Pearson 1900"
  },
  "ll": {
    "name": "Log-Likelihood (G^2)",
    "latex_formula": "2 \\sum_{ij} O_{ij}\\,\\ln\\!\\left(\\frac{O_{ij}}{E_{ij}}\\right)",
    "smoothing": "none",
    "sort_key": "ll",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mn>2</mn><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mi>ln</mi><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Dunning's log-likelihood statistic (G²) over the complete 2x2 contingency table, more robust than chi-square also at small frequencies. G² measures significance, not effect size: in large corpora even trivial differences become highly significant.",
    "reference": "Dunning 1993"
  },
  "delta_p_nc": {
    "name": "Delta P (node -> collocate)",
    "latex_formula": "\\Delta P_{n\\to c} = P(c \\mid n) - P(c \\mid \\lnot n) = \\frac{O_{11}}{R_1} - \\frac{C_1 - O_{11}}{N_\\Omega - R_1}",
    "smoothing": "none",
    "sort_key": "delta_p_nc",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>&#916;</mi><mrow><mi>n</mi><mo>&#8594;</mo><mi>c</mi></mrow></msub><mi>P</mi><mo>=</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>R</mi><mn>1</mn></msub></mfrac><mo>&#8722;</mo><mfrac><mrow><msub><mi>C</mi><mn>1</mn></msub><mo>&#8722;</mo><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>N</mi><mi>&#937;</mi></msub><mo>&#8722;</mo><msub><mi>R</mi><mn>1</mn></msub></mrow></mfrac></math>",
    "explanation": "Asymmetric association measure: difference between the probability of the collocate with and without the node, range −1 to 1. Captures directional effects that symmetric measures such as MI or Dice hide.",
    "reference": "Allan 1980; Ellis 2006; Gries 2013"
  },
  "delta_p_cn": {
    "name": "Delta P (collocate -> node)",
    "latex_formula": "\\Delta P_{c\\to n} = P(n \\mid c) - P(n \\mid \\lnot c) = \\frac{O_{11}}{C_1} - \\frac{R_1 - O_{11}}{N_\\Omega - C_1}",
    "smoothing": "none",
    "sort_key": "delta_p_cn",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>&#916;</mi><mrow><mi>c</mi><mo>&#8594;</mo><mi>n</mi></mrow></msub><mi>P</mi><mo>=</mo><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>C</mi><mn>1</mn></msub></mfrac><mo>&#8722;</mo><mfrac><mrow><msub><mi>R</mi><mn>1</mn></msub><mo>&#8722;</mo><msub><mi>O</mi><mn>11</mn></msub></mrow><mrow><msub><mi>N</mi><mi>&#937;</mi></msub><mo>&#8722;</mo><msub><mi>C</mi><mn>1</mn></msub></mrow></mfrac></math>",
    "explanation": "Opposite direction of Delta P: difference between the probability of the node with and without the collocate, range −1 to 1. Together with the forward direction it shows which partner predicts the other more strongly.",
    "reference": "Allan 1980; Ellis 2006; Gries 2013"
  },
  "chi2": {
    "name": "Chi-square (2x2 Pearson, df=1)",
    "latex_formula": "\\chi^2 = \\sum_{ij} \\frac{(O_{ij} - E_{ij})^2}{E_{ij}},\\quad E_{ij} = \\frac{\\text{row}_i \\cdot \\text{col}_j}{N}",
    "smoothing": "none",
    "sort_key": "chi2",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msup><mi>&#967;</mi><mn>2</mn></msup><mo>=</mo><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><mfrac><mrow><msup><mrow><mo>(</mo><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>&#8722;</mo><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>)</mo></mrow><mn>2</mn></msup></mrow><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac></math>",
    "explanation": "Pearson's chi-square test over the complete 2x2 table (df=1). A pure significance measure without effect size. With expected cell counts below 5 the approximation is unreliable (see expected_min).",
    "reference": "Pearson 1900"
  },
  "chi2_signed": {
    "name": "Signed chi-square (2x2 Pearson)",
    "latex_formula": "\\operatorname{sign}(\\Delta_{pm}) \\cdot \\sum_{ij} \\frac{(O_{ij} - E_{ij})^2}{E_{ij}}",
    "smoothing": "none",
    "sort_key": "chi2_signed",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>sign</mi><mrow><mo>(</mo><msub><mi>&#916;</mi><mrow><mi>p</mi><mi>m</mi></mrow></msub><mo>)</mo></mrow><mo>&#8901;</mo><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><mfrac><mrow><msup><mrow><mo>(</mo><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>&#8722;</mo><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>)</mo></mrow><mn>2</mn></msup></mrow><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac></math>",
    "explanation": "Chi-square with the sign of the frequency difference: positive values show overrepresentation in the target corpus, negative values in the reference corpus. The absolute value reads like chi2 (significance, not effect size).",
    "reference": "Pearson 1900"
  },
  "ll_signed": {
    "name": "Signed log-likelihood",
    "latex_formula": "\\operatorname{sign}(\\Delta_{pm}) \\cdot 2 \\sum_{ij} O_{ij}\\,\\ln\\!\\left(\\frac{O_{ij}}{E_{ij}}\\right)",
    "smoothing": "none",
    "sort_key": "ll_signed",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>sign</mi><mrow><mo>(</mo><msub><mi>&#916;</mi><mrow><mi>p</mi><mi>m</mi></mrow></msub><mo>)</mo></mrow><mo>&#8901;</mo><mn>2</mn><munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mi>ln</mi><mrow><mo>(</mo><mfrac><msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></mfrac><mo>)</mo></mrow></math>",
    "explanation": "G² with the sign of the frequency difference: positive values mean overrepresentation in the target corpus, negative values in the reference corpus. Like the undirected G², a statement about significance, not effect size.",
    "reference": "Dunning 1993"
  },
  "log_ratio": {
    "name": "Log Ratio (Hardie)",
    "latex_formula": "\\log_2\\!\\left(\\frac{(O_{11}+0.5)/N_t}{(O_{21}+0.5)/N_r}\\right)",
    "smoothing": "Haldane-Anscombe +0.5",
    "sort_key": "log_ratio",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>log</mi><mn>2</mn></msub><mrow><mo>(</mo><mfrac><mrow><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>+</mo><mn>0.5</mn></mrow><msub><mi>N</mi><mi>t</mi></msub></mfrac></mrow><mrow><mfrac><mrow><msub><mi>O</mi><mn>21</mn></msub><mo>+</mo><mn>0.5</mn></mrow><msub><mi>N</mi><mi>r</mi></msub></mfrac></mrow></mfrac><mo>)</mo></mrow></math>",
    "explanation": "Binary logarithm of the ratio of relative frequencies (effect size): +1 corresponds to twice the frequency in the target corpus. Log Ratio makes no statement about significance and is therefore combined with a significance measure (G², BIC). The +0.5 smoothing keeps one-sided zero cells finite.",
    "reference": "Hardie 2014"
  },
  "lrc": {
    "name": "Conservative Log Ratio (Evert 2022)",
    "latex_formula": "\\mathrm{LRC} = \\operatorname{sign}(\\widehat{LR}) \\cdot \\max\\left(0, \\left|\\text{bound closer to zero of }\\mathrm{CI}_{1-\\alpha}(LR)\\right|\\right)",
    "smoothing": "none",
    "sort_key": "lrc",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>LRC</mi><mo>=</mo><mi>sgn</mi><mo>(</mo><msub><mi>LR</mi><mn>0</mn></msub><mo>)</mo><mo>&#183;</mo><mi>min</mi><mrow><mo>|</mo><msub><mi>log</mi><mn>2</mn></msub><mfrac><mrow><msub><mi>O</mi><mn>11</mn></msub><mo>/</mo><msub><mi>R</mi><mn>1</mn></msub></mrow><mrow><msub><mi>O</mi><mn>21</mn></msub><mo>/</mo><mo>(</mo><mi>N</mi><mo>-</mo><msub><mi>R</mi><mn>1</mn></msub><mo>)</mo></mrow></mfrac><mo>|</mo></mrow></math>",
    "explanation": "Conservative Log Ratio: the bound of the confidence interval for the Log Ratio that lies CLOSER TO ZERO, that is, the smallest effect size compatible with the data. If the interval includes zero, the effect cannot be separated from zero and the LRC is 0. This is why it does not push rare candidates to the top: a single occurrence produces a wide interval and therefore an LRC of 0. The interval is EXACT and conditional on the marginal total (Clopper-Pearson), not a normal approximation. The Bonferroni correction runs over the number of candidates tested at the same time (lrc_tests in the method card), the level is lrc_alpha. On the collocation surface the marginal totals are Evert's distance table: target rate O11/|W(u)|, reference rate (f(v)-O11)/(N-|W(u)|). In keyness it compares target and reference: a/N_t against c/N_r.",
    "reference": "Evert 2022; Clopper & Pearson 1934"
  },
  "bic": {
    "name": "Bayes Information Criterion",
    "latex_formula": "G^2 - \\ln(N_t + N_r)",
    "smoothing": "none",
    "sort_key": "bic",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msup><mi>G</mi><mn>2</mn></msup><mo>&#8722;</mo><mi>ln</mi><mrow><mo>(</mo><msub><mi>N</mi><mi>t</mi></msub><mo>+</mo><msub><mi>N</mi><mi>r</mi></msub><mo>)</mo></mrow></math>",
    "explanation": "Bayesian information criterion approximated from G²: values above about 2 count as positive evidence, above about 10 as very strong evidence against independence. Unlike the p-value, the BIC penalizes corpus size and does not automatically become significant in large corpora.",
    "reference": "Wilson 2013"
  },
  "p_value": {
    "name": "p-value (chi-square, df=1)",
    "latex_formula": "P(\\chi^2_1 \\ge G^2)",
    "smoothing": "none",
    "sort_key": "p_value",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>P</mi><mrow><mo>(</mo><msubsup><mi>&#967;</mi><mn>1</mn><mn>2</mn></msubsup><mo>&#8805;</mo><msup><mi>G</mi><mn>2</mn></msup><mo>)</mo></mrow></math>",
    "explanation": "Probability of observing a G² value at least this large under the null hypothesis of independence (chi-square distribution, df=1). With many parallel tests the raw p-value is misleading without correction (see q-value).",
    "reference": "Dunning 1993"
  },
  "q_value": {
    "name": "q-value (FDR, Benjamini-Hochberg)",
    "latex_formula": "q_{(i)} = \\min_{k \\ge i}\\ \\frac{m \\cdot p_{(k)}}{k}",
    "smoothing": "none",
    "sort_key": "q_value",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>q</mi><mrow><mo>(</mo><mi>i</mi><mo>)</mo></mrow></msub><mo>=</mo><munder><mi>min</mi><mrow><mi>k</mi><mo>&#8805;</mo><mi>i</mi></mrow></munder><mfrac><mrow><mi>m</mi><mo>&#8901;</mo><msub><mi>p</mi><mrow><mo>(</mo><mi>k</mi><mo>)</mo></mrow></msub></mrow><mi>k</mi></mfrac></math>",
    "explanation": "Benjamini-Hochberg adjusted p-value: controls the expected false discovery rate (FDR) over all expressions tested at the same time. Preferable to the raw p-value for keyword lists with many tests.",
    "reference": "Benjamini & Hochberg 1995"
  },
  "diff_per_million": {
    "name": "Difference per million",
    "latex_formula": "\\frac{O_{11}}{N_t}\\cdot 10^6 - \\frac{O_{21}}{N_r}\\cdot 10^6",
    "smoothing": "none",
    "sort_key": "diff_per_million",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>N</mi><mi>t</mi></msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup><mo>&#8722;</mo><mfrac><msub><mi>O</mi><mn>21</mn></msub><msub><mi>N</mi><mi>r</mi></msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup></math>",
    "explanation": "Difference between the frequencies per million tokens in the target and the reference corpus. A descriptive measure without a statement about significance. The absolute value depends strongly on the base frequency of the expression.",
    "reference": "Brezina 2018"
  },
  "expected_min": {
    "name": "Smallest expected cell count E_min",
    "latex_formula": "E_{\\min} = \\min_{ij} E_{ij},\\quad E_{ij} = \\frac{\\text{row}_i \\cdot \\text{col}_j}{N}",
    "smoothing": "none",
    "sort_key": "expected_min",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>E</mi><mi>min</mi></msub><mo>=</mo><munder><mi>min</mi><mrow><mi>i</mi><mi>j</mi></mrow></munder><msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub></math>",
    "explanation": "Smallest expected cell count of the 2x2 table. A diagnostic for the validity of the asymptotic tests: below 5, the chi-square approximation is unreliable.",
    "reference": "Cochran 1954"
  },
  "low_reliability": {
    "name": "Low reliability (E_min < 5)",
    "latex_formula": "\\mathbb{1}\\!\\left[E_{\\min} < 5\\right]",
    "smoothing": "none",
    "sort_key": "low_reliability",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>&#120793;</mi><mrow><mo>[</mo><msub><mi>E</mi><mi>min</mi></msub><mo>&lt;</mo><mn>5</mn><mo>]</mo></mrow></math>",
    "explanation": "Flag that at least one expected cell count is below 5. The asymptotic test statistics (chi2, G²) are of limited reliability for such rows.",
    "reference": "Cochran 1954"
  },
  "frequency": {
    "name": "Frequency",
    "latex_formula": "f = \\#\\{\\text{occurrences}\\}",
    "smoothing": "none",
    "sort_key": "freq",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>f</mi><mo>=</mo><mo>#</mo><mrow><mo>{</mo><mtext>occurrences</mtext><mo>}</mo></mrow></math>",
    "explanation": "Raw frequency of occurrence in the selected scope. Comparisons between corpora or subcorpora of different sizes require normalized frequencies (per million).",
    "reference": "Brezina 2018"
  },
  "ttr": {
    "name": "Type-Token Ratio",
    "latex_formula": "\\mathrm{TTR} = \\frac{V}{N}",
    "smoothing": "none",
    "sort_key": "ttr",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mi>V</mi><mi>N</mi></mfrac></math>",
    "explanation": "Ratio of types (V) to tokens (N) as a measure of lexical diversity. Strongly dependent on text length: longer texts systematically get lower values, and direct comparisons require equal lengths or standardized variants (STTR, MATTR).",
    "reference": "Brezina 2018"
  },
  "sttr": {
    "name": "Standardised TTR",
    "latex_formula": "\\mathrm{STTR} = \\frac{1}{W}\\sum_{w=1}^{W} \\frac{V_w}{n}\\quad (n = \\text{window size})",
    "smoothing": "none",
    "sort_key": "sttr",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mn>1</mn><mi>W</mi></mfrac><munderover><mo>&#8721;</mo><mrow><mi>w</mi><mo>=</mo><mn>1</mn></mrow><mi>W</mi></munderover><mfrac><msub><mi>V</mi><mi>w</mi></msub><mi>n</mi></mfrac></math>",
    "explanation": "Mean TTR over consecutive text windows of equal size. It neutralizes the length dependence of the raw TTR. A remaining window shorter than the window size is not counted.",
    "reference": "Scott, WordSmith Tools"
  },
  "guiraud": {
    "name": "Guiraud's R",
    "latex_formula": "R = \\frac{V}{\\sqrt{N}}",
    "smoothing": "none",
    "sort_key": "guiraud",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mi>V</mi><msqrt><mi>N</mi></msqrt></mfrac></math>",
    "explanation": "Square-root transformed type-token relation (V/√N). Reduces the length dependence of the TTR but does not remove it completely.",
    "reference": "Guiraud 1954"
  },
  "mattr": {
    "name": "Moving-Average TTR",
    "latex_formula": "\\mathrm{MATTR} = \\frac{1}{N - n + 1}\\sum_{i=1}^{N-n+1}\\frac{V_i}{n}",
    "smoothing": "none",
    "sort_key": "mattr",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mn>1</mn><mrow><mi>N</mi><mo>&#8722;</mo><mi>n</mi><mo>+</mo><mn>1</mn></mrow></mfrac><munderover><mo>&#8721;</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mrow><mi>N</mi><mo>&#8722;</mo><mi>n</mi><mo>+</mo><mn>1</mn></mrow></munderover><mfrac><msub><mi>V</mi><mi>i</mi></msub><mi>n</mi></mfrac></math>",
    "explanation": "TTR over a moving window of fixed length, averaged over all window positions. Largely independent of length and finer-grained than the block-wise STTR.",
    "reference": "Covington & McFall 2010"
  },
  "dp": {
    "name": "Gries DP (Deviation of Proportions)",
    "latex_formula": "\\mathrm{DP} = \\tfrac{1}{2}\\sum_i\\left|\\frac{o_i}{F} - \\frac{s_i}{N}\\right|",
    "smoothing": "none",
    "sort_key": "dp",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mn>1</mn><mn>2</mn></mfrac><munder><mo>&#8721;</mo><mi>i</mi></munder><mrow><mo>|</mo><mfrac><msub><mi>o</mi><mi>i</mi></msub><mi>F</mi></mfrac><mo>&#8722;</mo><mfrac><msub><mi>s</mi><mi>i</mi></msub><mi>N</mi></mfrac><mo>|</mo></mrow></math>",
    "explanation": "Deviation of the observed shares of hits from the shares expected from document size: 0 means an even distribution, values towards 1 a concentration in few documents. Complements frequency measures, which hide such clustering.",
    "reference": "Gries 2008"
  },
  "dpnorm": {
    "name": "Gries DPnorm (normalized)",
    "latex_formula": "\\mathrm{DP_{norm}} = \\frac{\\mathrm{DP}}{1 - \\min_i (s_i / N)}",
    "smoothing": "none",
    "sort_key": "dpnorm",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mi>DP</mi><mrow><mn>1</mn><mo>&#8722;</mo><munder><mi>min</mi><mi>i</mi></munder><mrow><mo>(</mo><mfrac><msub><mi>s</mi><mi>i</mi></msub><mi>N</mi></mfrac><mo>)</mo></mrow></mrow></mfrac></math>",
    "explanation": "DP normalized to its attainable maximum. This makes it comparable between corpora with different numbers and sizes of parts.",
    "reference": "Lijffijt & Gries 2012"
  },
  "juilland_d": {
    "name": "Juilland's D",
    "latex_formula": "D = 1 - \\frac{\\mathrm{VC}}{\\sqrt{n - 1}},\\quad \\mathrm{VC} = \\frac{\\sigma(v_i)}{\\bar{v}},\\ v_i = \\frac{o_i}{s_i}",
    "smoothing": "none",
    "sort_key": "juilland_d",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>D</mi><mo>=</mo><mn>1</mn><mo>&#8722;</mo><mfrac><mi>VC</mi><msqrt><mrow><mi>n</mi><mo>&#8722;</mo><mn>1</mn></mrow></msqrt></mfrac></math>",
    "explanation": "Classic dispersion measure based on the coefficient of variation of the size-normalized part frequencies. 1 means a perfectly even distribution. With many small parts, D tends to overestimate evenness.",
    "reference": "Juilland & Chang-Rodríguez 1964"
  },
  "carroll_d2": {
    "name": "Carroll's D2 (normalized entropy)",
    "latex_formula": "D_2 = \\frac{H}{\\ln n},\\quad H = -\\sum_i p_i \\ln p_i,\\ p_i = \\frac{o_i}{F}",
    "smoothing": "none",
    "sort_key": "carroll_d2",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><msub><mi>D</mi><mn>2</mn></msub><mo>=</mo><mfrac><mi>H</mi><mrow><mi>ln</mi><mi>n</mi></mrow></mfrac><mo>,</mo><mi>H</mi><mo>=</mo><mo>&#8722;</mo><munder><mo>&#8721;</mo><mi>i</mi></munder><msub><mi>p</mi><mi>i</mi></msub><mi>ln</mi><msub><mi>p</mi><mi>i</mi></msub></math>",
    "explanation": "Normalized entropy of the distribution of hits over the parts: 1 means a uniform distribution, 0 complete concentration in one part. Unlike Range, it also takes the frequency shares into account.",
    "reference": "Carroll 1970"
  },
  "range_prop": {
    "name": "Range (share of parts reached)",
    "latex_formula": "\\mathrm{Range} = \\frac{\\#\\{i : o_i > 0\\}}{n}",
    "smoothing": "none",
    "sort_key": "range_prop",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mo>#</mo><mrow><mo>{</mo><mi>i</mi><mo>:</mo><msub><mi>o</mi><mi>i</mi></msub><mo>&gt;</mo><mn>0</mn><mo>}</mo></mrow></mrow><mi>n</mi></mfrac></math>",
    "explanation": "Share of parts (documents) in which the expression occurs at least once. A robust but coarse dispersion measure: frequency differences within the parts are not taken into account.",
    "reference": "Brezina 2018"
  },
  "vc": {
    "name": "Coefficient of variation (VC)",
    "latex_formula": "\\mathrm{VC} = \\frac{\\sigma(v_i)}{\\bar{v}},\\ v_i = \\frac{o_i}{s_i}",
    "smoothing": "none",
    "sort_key": "vc",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mi>&#963;</mi><mrow><mo>(</mo><msub><mi>v</mi><mi>i</mi></msub><mo>)</mo></mrow></mrow><mover><mi>v</mi><mo>&#175;</mo></mover></mfrac><mo>,</mo><msub><mi>v</mi><mi>i</mi></msub><mo>=</mo><mfrac><msub><mi>o</mi><mi>i</mi></msub><msub><mi>s</mi><mi>i</mi></msub></mfrac></math>",
    "explanation": "Coefficient of variation of the size-normalized part frequencies, the basis of Juilland's D. Higher values mean a less even distribution over the parts.",
    "reference": "Juilland & Chang-Rodríguez 1964"
  },
  "per_million": {
    "name": "Hits per million (period)",
    "latex_formula": "\\mathrm{pM} = \\frac{h_p}{n_p}\\cdot 10^{6}",
    "smoothing": "none",
    "sort_key": "per_million",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><msub><mi>h</mi><mi>p</mi></msub><msub><mi>n</mi><mi>p</mi></msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup></math>",
    "explanation": "Normalized frequency per period: hits per million running tokens. Makes periods with different amounts of text comparable. With small token counts per period the value varies strongly (see confidence interval).",
    "reference": "Brezina 2018"
  },
  "wilson_ci": {
    "name": "Wilson confidence interval (95%)",
    "latex_formula": "\\frac{\\hat p + \\frac{z^2}{2n} \\pm z\\sqrt{\\frac{\\hat p(1-\\hat p)}{n} + \\frac{z^2}{4n^2}}}{1 + \\frac{z^2}{n}},\\quad \\hat p = \\frac{h_p}{n_p},\\ z = 1{,}96",
    "smoothing": "none",
    "sort_key": "per_million",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mfrac><mrow><mover><mi>p</mi><mo>^</mo></mover><mo>+</mo><mfrac><msup><mi>z</mi><mn>2</mn></msup><mrow><mn>2</mn><mi>n</mi></mrow></mfrac><mo>&#177;</mo><mi>z</mi><msqrt><mrow><mfrac><mrow><mover><mi>p</mi><mo>^</mo></mover><mrow><mo>(</mo><mn>1</mn><mo>&#8722;</mo><mover><mi>p</mi><mo>^</mo></mover><mo>)</mo></mrow></mrow><mi>n</mi></mfrac><mo>+</mo><mfrac><msup><mi>z</mi><mn>2</mn></msup><mrow><mn>4</mn><msup><mi>n</mi><mn>2</mn></msup></mrow></mfrac></mrow></msqrt></mrow><mrow><mn>1</mn><mo>+</mo><mfrac><msup><mi>z</mi><mn>2</mn></msup><mi>n</mi></mfrac></mrow></mfrac></math>",
    "explanation": "95% confidence interval (Wilson score) for the token rate of a period, scaled to per million. The interval is asymmetric and defined even for zero hits (lower bound 0). Narrow intervals require large token counts per period.",
    "reference": "Wilson 1927"
  },
  "random_sample": {
    "name": "Uniform random sample (thinning)",
    "latex_formula": "S \\subseteq \\{1,\\dots,N\\},\\ |S| = k = \\min(\\mathrm{sample},\\,N),\\quad P(i \\in S) = \\frac{k}{N}",
    "smoothing": "none",
    "sort_key": "pos",
    "formula_mathml": "<math xmlns=\"http://www.w3.org/1998/Math/MathML\" display=\"inline\"><mi>P</mi><mrow><mo>(</mo><mi>i</mi><mo>&#8712;</mo><mi>S</mi><mo>)</mo></mrow><mo>=</mo><mfrac><mi>k</mi><mi>N</mi></mfrac><mo>,</mo><mi>k</mi><mo>=</mo><mi>min</mi><mrow><mo>(</mo><mtext>sample</mtext><mo>,</mo><mi>N</mi><mo>)</mo></mrow></math>",
    "explanation": "Uniform random sample without replacement from all hits, reproducible through the given seed. Statistics over the sample estimate the full set with sampling error. The provenance (requested, drawn, seed, population) is included.",
    "reference": "Brezina 2018"
  },
}
// i18n-ignore-end

/** Nachschlag mit Normalisierung von UI-Schreibweisen auf Katalog-Keys. */
const UI_KEY_ALIASES: Record<string, string> = {
  // Kollokations-Picker: 'tscore' (UI) -> 't' (Katalog/sort_key).
  tscore: 't',
  // Ko-Okkurrenz-Haeufigkeit im Kollokations-Picker -> Frequenz-Eintrag.
  f: 'frequency',
}

export function measureCatalogEntry(
  key: string | null | undefined,
  locale: AppLocale = currentLocale(),
): MeasureCatalogEntry | null {
  if (!key) return null
  const catalog = locale === 'en' ? MEASURE_CATALOG_EN : MEASURE_CATALOG
  const normalized = key.trim().toLowerCase()
  const resolved = catalog[normalized] ?? catalog[UI_KEY_ALIASES[normalized] ?? '']
  return resolved ?? null
}
