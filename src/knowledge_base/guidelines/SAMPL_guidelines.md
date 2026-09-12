Statistical Analyses and Methods in the Published Literature (SAMPL) Guidelines

Target Agents: Agent 1 (Copy Editor), Agent 4 (Biostatistician)
Purpose: Enforce rigorous statistical reporting standards in medical and health sciences manuscripts.

1. General Principles

Reproducibility: Statistical methods must be described with enough detail that a knowledgeable reader with access to the original data could verify the reported results.

Software: Identify the statistical software package(s) and versions used (e.g., R version 4.2.1, Stata/MP 17.0).

A Priori vs. Post Hoc: Clearly distinguish between prespecified (a priori) analyses and exploratory (post hoc) analyses.

2. Reporting Numbers and Descriptive Statistics

Significant Digits: Report numbers to the appropriate degree of precision. For clinical measurements, do not exceed the precision of the measuring instrument. Percentages should generally be reported to one decimal place (e.g., 45.2%), unless N < 100, where whole numbers are preferred.

Continuous Variables:

Normally distributed data: Report Mean and Standard Deviation (Mean ± SD).

Non-normally distributed data: Report Median and Interquartile Range (Median [IQR] or Median [25th-75th percentiles]). Do not use standard error of the mean (SEM) to describe data variability.

Categorical Variables: Report as frequencies and percentages: n (%). Include the denominator if there is missing data.

3. Hypothesis Testing and P-Values

Exact P-Values: Report exact p-values to two or three decimal places (e.g., p = 0.034, p = 0.65).

Thresholds: Do not use inequalities (e.g., p < 0.05 or NS) unless the p-value is extremely small (e.g., p < 0.001).

Binary Interpretation: A result is either statistically significant (based on the prespecified alpha, usually 0.05) or it is not. Flag and reject phrases like "approaching significance," "borderline significance," or "trending toward significance."

4. Estimates of Effect and Confidence Intervals (CIs)

Primacy of CIs: Hypothesis testing (p-values) must be accompanied by effect size estimates and their 95% Confidence Intervals (95% CI). CIs provide information on clinical relevance and precision that p-values lack.

Risk and Association: Always report point estimates (Odds Ratios [OR], Relative Risks [RR], Hazard Ratios [HR], Absolute Risk Reduction [ARR]) alongside their 95% CIs.

Formatting: E.g., "OR = 2.4 (95% CI, 1.2 to 4.8); p = 0.012".

5. Regression and Advanced Modeling

Model Specification: Explicitly define the dependent (outcome) variable and all independent (predictor) variables.

Variable Selection: State the criteria used to include variables in multivariable models (e.g., clinical relevance, p < 0.20 in univariable screening, stepwise selection [though stepwise is generally discouraged]).

Unadjusted vs. Adjusted: Present both unadjusted (crude) and adjusted models when evaluating interventions or exposures.

Assumptions: State that the underlying assumptions of the models (e.g., proportional hazards for Cox models, linearity for logistic regression) were tested and met.

6. Missing Data and Sample Size

Power Calculation: Every prospective study and clinical trial must report an a priori sample size/power calculation. Retrospective studies should acknowledge sample size limitations rather than performing post hoc power calculations.

Handling Missing Data: Explicitly state the amount of missing data for key variables. Describe how missing data were handled (e.g., complete case analysis/listwise deletion, multiple imputation).

7. Multiplicity (Multiple Comparisons)

Adjustment: If multiple primary endpoints are tested, or if multiple subgroup comparisons are made, state whether and how the threshold for statistical significance was adjusted (e.g., Bonferroni correction, False Discovery Rate).