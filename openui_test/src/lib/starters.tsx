import { PromptTemplate } from "@openuidev/react-ui";
import { BarChart3, Building2, Globe2, ShoppingCart } from "lucide-react";

export const BRAND_LOGOS = {
  LIGHT: "/queryable-logo-light.svg",
  DARK: "/queryable-logo-dark.svg",
};

export const PROMPT_TEMPLATES: PromptTemplate[] = [
  {
    displayText: "Geography",
    prompt: "",
    icon: <Globe2 size={16} />,
    completions: [
      {
        displayText: "Companies per country on a map",
        prompt: "Show the number of companies per country",
        icon: <></>,
      },
      {
        displayText: "Where are our customers?",
        prompt: "Show the number of customers per country",
        icon: <></>,
      },
      {
        displayText: "Which country does a company belong to?",
        prompt: "Which country does Professional Services Company 001 belong to?",
        icon: <></>,
      },
    ],
  },
  {
    displayText: "Companies & HR tech",
    prompt: "",
    icon: <Building2 size={16} />,
    completions: [
      {
        displayText: "Average annual HR tech spend by deployment type",
        prompt: "Compare the average annual HR technology spend by deployment type",
        icon: <></>,
      },
      {
        displayText: "Top 5 countries by total HR tech spend",
        prompt: "Show total annual HR tech spend by country for the top 5 countries",
        icon: <></>,
      },
      {
        displayText: "Most used HR technologies",
        prompt: "Which HR technologies are used by the most companies? Show the top 8",
        icon: <></>,
      },
    ],
  },
  {
    displayText: "Sales & orders",
    prompt: "",
    icon: <ShoppingCart size={16} />,
    completions: [
      {
        displayText: "Order count by status",
        prompt: "How many orders are there in each order status?",
        icon: <></>,
      },
      {
        displayText: "Monthly revenue trend",
        prompt: "Show total revenue per month in 2024 from sales",
        icon: <></>,
      },
      {
        displayText: "Customers by country",
        prompt: "Show the number of customers per country",
        icon: <></>,
      },
    ],
  },
];

export const STARTERS = [
  {
    displayText: "How many companies are in India?",
    prompt: "How many companies are in India?",
    icon: <BarChart3 size={14} />,
  },
  {
    displayText: "Companies per country on a map",
    prompt: "Show the number of companies per country",
    icon: <Globe2 size={14} />,
  },
  {
    displayText: "HR tech spend by deployment type",
    prompt: "Compare the average annual HR technology spend by deployment type",
    icon: <BarChart3 size={14} />,
  },
  {
    displayText: "Explain SaaS vs on-premise",
    prompt: "What is the difference between SaaS and on-premise software?",
    icon: <></>,
  },
];
