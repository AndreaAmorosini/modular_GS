import streamlit as st

st.set_page_config(
    page_title = "Modular Gaussian Splatting - Home",
    layout = "wide",
    page_icon = "🏠"
)

st.title("Welcome to Modular Gaussian Splatting!")
st.markdown("""
This is the home page of the Modular Gaussian Splatting web interface. Use the sidebar to navigate between pages and manage your methods and pipelines.
""")

#TODO: Magari mettere bottoni per accedere alle varie pagine oltre al menu