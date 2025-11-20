import streamlit as st

def two_column_form():
    return st.columns(2)

def small_info(msg):
    st.info(msg)
