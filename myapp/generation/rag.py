import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


class RAGGenerator:
    """
    Retrieval-Augmented Generation helper that takes a user query and a list of
    retrieved product objects and asks an LLM to pick the best product.
    """

    # Improved prompt
    PROMPT_TEMPLATE = """
        You are a product expert helping a user choose from a list of retrieved products.

        Rules:
        - You MUST choose the best product ONLY from the list below.
        - Do NOT invent products or features that are not mentioned.
        - Refer to products only by their Name (not by ID).
        - Do not use Women or Men to decide unless it is mentioned in the user request
        - When comparing products, strongly prefer items that are IN STOCK and explicitly mention it in your explanation.
        - If a product is OUT OF STOCK, you may only choose it if there is no clearly suitable in-stock alternative.
        - If a product has a DISCOUNT, explicitly mention it in your explanation and treat it as a positive aspect when relevant.
        - In your explanations, use concrete attributes such as category, brand, price, discount, stock, size, color, material and rating.
        - Be specific and detailed about WHY the best product fits the user's request and WHY the alternative could also be a good option.

        Retrieved products:
        {retrieved_results}

        User request:
        {user_query}

        Output (use exactly these labels):
        Best product: <name of the best product, or "none">
        Why: <2–4 sentences explaining in detail why this product is the best match, using concrete attributes (including stock and discount if present)>
        Be carefull: <1 sentence explaining in detail one bad thing about the product best match, try to use concrete attributes (including stock and discount if present)>
        Alternative: <1–3 sentences giving a second good option from the list, again using concrete attributes and mentioning stock/discount when relevant>

        If no product fits, set only this next text:
        No results for this search, maybe try: <recomend a similar search to the user, always related to the clothing products, if user request is empty, encourage the user to search in the clothing products>"""

    # Function to pass the features to the AI
    def _format_product(self, res) -> str:

        lines = []

        # Core identifiers
        pid = getattr(res, "pid", None) or getattr(res, "id", None)
        title = getattr(res, "title", None) or getattr(res, "name", None)

        header_parts = []
        if title:
            header_parts.append(f"Name: {title}")
        if pid:
            header_parts.append(f"ID: {pid}")
        if header_parts:
            lines.append(" - " + " | ".join(header_parts))

        def add_field(label: str, attr: str):
            value = getattr(res, attr, None)
            if value not in (None, "", [], {}):
                lines.append(f"   {label}: {value}")

        add_field("Brand", "brand")
        add_field("Category", "category")
        add_field("Subcategory", "subcategory")
        add_field("Price", "price")
        add_field("Color", "color")
        add_field("Rating", "rating")
        add_field("Stock", "stock")
        add_field("Discount", "discount")

        # Description (truncated to avoid huge prompts)
        desc = getattr(res, "description", None) or getattr(res, "short_description", None)
        if desc:
            desc = str(desc)
            if len(desc) > 220:
                desc = desc[:217] + "..."
            lines.append(f"   Description: {desc}")

        score = getattr(res, "score", None)
        if score is not None:
            lines.append(f"   Retrieval score: {score}")

        return "\n".join(lines)

    def generate_response(self, user_query: str, retrieved_results: list, top_N: int = 20) -> str:
        """
        Generate a natural-language recommendation using the retrieved search results.

        Args:
            user_query (str): Original query from the user.
            retrieved_results (list): List of retrieved product objects.
            top_N (int): Maximum number of results to include in the prompt.

        Returns:
            str: The generated answer from the LLM, or a default error message.
        """
        DEFAULT_ANSWER = "RAG is not available. Check your credentials (.env file) or account limits."
        try:
            client = Groq(
                api_key=os.environ.get("GROQ_API_KEY"),
            )
            model_name = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

            # Use richer data instead of only PID + title
            top_results = retrieved_results[:top_N] if retrieved_results else []
            formatted_results = "\n".join(
                self._format_product(res) for res in top_results
            ) if top_results else "No products were retrieved."

            # Plug rich results into the refined prompt
            prompt = self.PROMPT_TEMPLATE.format(
                retrieved_results=formatted_results,
                user_query=user_query,
            )

            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=model_name,
            )

            generation = chat_completion.choices[0].message.content
            return generation
        except Exception as e:
            print(f"Error during RAG generation: {e}")
            return DEFAULT_ANSWER

